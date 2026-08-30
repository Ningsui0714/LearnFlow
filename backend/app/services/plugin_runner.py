"""Bounded JSON-RPC broker for explicitly enabled native plugin runners.

This broker reduces ambient authority (fixed argv, clean environment and
capability checked host calls) but does *not* provide an OS sandbox.  Its
boundary disclosure therefore remains false for filesystem, network and
secret isolation on every run.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence


RPC_PROTOCOL = "learnflow.plugin-rpc.v1"
EXECUTION_BOUNDARY = {
    "mode": "trusted_signed_process",
    "execution_mode": "trusted_signed_process",
    "filesystem_isolation": False,
    "network_isolation": False,
    "secrets_isolation": False,
    "cpu_isolation": False,
    "memory_isolation": False,
    "native_process": True,
    "environment_sanitized": True,
    "descendant_cleanup_guaranteed": os.name != "nt",
    "process_tree_boundary": "posix_process_group" if os.name != "nt" else "windows_best_effort_process_group",
}
_SAFE_PARENT_ENV = {
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
}


class PluginRunnerError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        boundary: Mapping[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.boundary = dict(boundary or {**EXECUTION_BOUNDARY, "executed": False})


@dataclass(frozen=True)
class PluginRunnerConfig:
    execution_mode: str = "disabled"
    environment: str = "production"
    allow_unsigned_development: bool = False
    timeout_seconds: float = 600.0
    max_message_bytes: int = 256 * 1024
    max_output_bytes: int = 1024 * 1024
    max_host_calls: int = 32

    @classmethod
    def from_settings(cls, settings: Any) -> "PluginRunnerConfig":
        return cls(
            execution_mode=str(getattr(settings, "plugin_execution_mode", "disabled")),
            environment=str(getattr(settings, "plugin_environment", "") or (
                "development" if bool(getattr(settings, "dev_test_login_enabled", False)) else "production"
            )),
            allow_unsigned_development=bool(
                getattr(settings, "plugin_allow_unsigned_dev", False)
            ),
            timeout_seconds=float(
                getattr(settings, "plugin_runner_timeout_seconds", 600.0)
            ),
            max_message_bytes=int(
                getattr(settings, "plugin_runner_max_message_bytes", 256 * 1024)
            ),
            max_output_bytes=int(
                getattr(settings, "plugin_runner_max_output_bytes", 1024 * 1024)
            ),
            max_host_calls=int(getattr(settings, "plugin_runner_max_host_calls", 32)),
        )

    def normalized(self) -> "PluginRunnerConfig":
        return PluginRunnerConfig(
            execution_mode=self.execution_mode,
            environment=self.environment,
            allow_unsigned_development=self.allow_unsigned_development,
            timeout_seconds=max(0.1, min(float(self.timeout_seconds), 600.0)),
            max_message_bytes=max(128, min(int(self.max_message_bytes), 256 * 1024)),
            max_output_bytes=max(512, min(int(self.max_output_bytes), 1024 * 1024)),
            max_host_calls=max(0, min(int(self.max_host_calls), 32)),
        )


@dataclass(frozen=True)
class PluginRunResult:
    result: Any
    events: tuple[dict[str, Any], ...]
    stderr: str
    exit_code: int
    host_call_count: int
    elapsed_seconds: float
    execution_boundary: dict[str, Any] = field(default_factory=lambda: dict(EXECUTION_BOUNDARY))


HostPortHandler = Callable[[str, dict[str, Any]], Any | Awaitable[Any]]


def sanitized_plugin_environment(workdir: str | Path) -> dict[str, str]:
    """Return a minimal environment without application credentials."""

    root = str(Path(workdir).resolve())
    env = {
        key: value
        for key in _SAFE_PARENT_ENV
        if (value := os.environ.get(key)) is not None
    }
    env.update(
        {
            "PATH": os.defpath,
            "HOME": root,
            "TMPDIR": root,
            "TMP": root,
            "TEMP": root,
            "XDG_CACHE_HOME": str(Path(root) / ".cache"),
            "XDG_CONFIG_HOME": str(Path(root) / ".config"),
            "XDG_DATA_HOME": str(Path(root) / ".local" / "share"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    if os.name == "nt":
        env["USERPROFILE"] = root
    return env


def _encode_message(message: Mapping[str, Any], max_bytes: int) -> bytes:
    try:
        data = (
            json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PluginRunnerError("rpc_encoding_failed", "JSON-RPC message is not serializable") from exc
    if len(data) > max_bytes:
        raise PluginRunnerError("rpc_message_too_large", "JSON-RPC message exceeds size budget")
    return data


async def _send_message(
    writer: asyncio.StreamWriter | Any, message: Mapping[str, Any], max_bytes: int
) -> None:
    writer.write(_encode_message(message, max_bytes))
    try:
        await writer.drain()
    except (BrokenPipeError, ConnectionResetError) as exc:
        raise PluginRunnerError("runner_pipe_closed", "plugin runner closed its input") from exc


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    if os.name == "nt":
        if process.returncode is not None:
            return
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, ProcessLookupError):
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), timeout=0.5)
            return
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    if process.returncode is None:
        try:
            await asyncio.wait_for(process.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass
    # The group may still contain children after its leader exited.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    if process.returncode is None:
        try:
            await asyncio.wait_for(process.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


class _OutputState:
    def __init__(self, limit: int):
        self.limit = limit
        self.total = 0
        self.stderr = bytearray()

    def consume(self, data: bytes, *, stderr: bool = False) -> None:
        self.total += len(data)
        if self.total > self.limit:
            raise PluginRunnerError("runner_output_limited", "plugin runner exceeded output budget")
        if stderr:
            self.stderr.extend(data)


async def _pump_stdout(
    reader: asyncio.StreamReader,
    queue: asyncio.Queue[tuple[str, Any]],
    state: _OutputState,
    max_message_bytes: int,
) -> None:
    try:
        while True:
            try:
                line = await reader.readline()
            except (ValueError, asyncio.LimitOverrunError) as exc:
                raise PluginRunnerError(
                    "rpc_message_too_large", "plugin runner emitted an oversized JSON-RPC message"
                ) from exc
            if not line:
                await queue.put(("stdout_eof", None))
                return
            state.consume(line)
            if len(line) > max_message_bytes:
                raise PluginRunnerError(
                    "rpc_message_too_large", "plugin runner emitted an oversized JSON-RPC message"
                )
            if not line.endswith(b"\n"):
                raise PluginRunnerError("invalid_rpc", "plugin runner output must use NDJSON framing")
            await queue.put(("stdout", line))
    except Exception as exc:
        await queue.put(("error", exc))


async def _pump_stderr(
    reader: asyncio.StreamReader,
    queue: asyncio.Queue[tuple[str, Any]],
    state: _OutputState,
) -> None:
    try:
        while True:
            chunk = await reader.read(8192)
            if not chunk:
                await queue.put(("stderr_eof", None))
                return
            state.consume(chunk, stderr=True)
    except Exception as exc:
        await queue.put(("error", exc))


def _rpc_error(identifier: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": identifier, "error": error}


class PluginProcessBroker:
    def __init__(self, config: PluginRunnerConfig | None = None):
        self.config = (config or PluginRunnerConfig()).normalized()

    def _authorize_execution(self, trust_state: str) -> None:
        if self.config.execution_mode != "trusted_signed_process":
            raise PluginRunnerError(
                "plugin_execution_disabled",
                "native plugin execution is disabled by the operator",
            )
        if trust_state == "trusted_signed":
            return
        if (
            trust_state == "untrusted_development"
            and self.config.allow_unsigned_development
            and self.config.environment.casefold() in {"development", "dev", "test"}
        ):
            return
        raise PluginRunnerError(
            "plugin_release_not_trusted", "plugin release is not authorized for native execution"
        )

    @staticmethod
    def _runner_path(value: str | Path) -> Path:
        original = Path(value).expanduser()
        if original.is_symlink():
            raise PluginRunnerError("unsafe_runner", "plugin runner cannot be a symbolic link")
        try:
            resolved = original.resolve(strict=True)
        except OSError as exc:
            raise PluginRunnerError("runner_not_found", "plugin runner does not exist") from exc
        if not resolved.is_file():
            raise PluginRunnerError("runner_not_found", "plugin runner must be a regular file")
        if os.name != "nt" and not os.access(resolved, os.X_OK):
            raise PluginRunnerError("runner_not_executable", "plugin runner is not executable")
        return resolved

    async def run(
        self,
        runner_path: str | Path,
        operation_id: str,
        input_data: Mapping[str, Any] | None = None,
        *,
        declared_host_ports: Sequence[str] = (),
        granted_host_ports: Sequence[str] = (),
        host_port_handler: HostPortHandler | None = None,
        trust_state: str = "untrusted",
    ) -> PluginRunResult:
        """Run one workflow/tool request in one fresh native process."""

        self._authorize_execution(trust_state)
        runner = self._runner_path(runner_path)
        if not isinstance(operation_id, str) or not operation_id:
            raise PluginRunnerError("invalid_operation", "plugin operation id is required")
        declared = set(declared_host_ports)
        granted = set(granted_host_ports)
        started = time.monotonic()
        process: asyncio.subprocess.Process | None = None
        boundary = {**EXECUTION_BOUNDARY, "executed": True, "trust_state": trust_state}
        try:
            with tempfile.TemporaryDirectory(prefix="learnflow-plugin-run-") as raw_workdir:
                workdir = Path(raw_workdir)
                process_kwargs: dict[str, Any] = {
                    "cwd": str(workdir),
                    "env": sanitized_plugin_environment(workdir),
                    "stdin": asyncio.subprocess.PIPE,
                    "stdout": asyncio.subprocess.PIPE,
                    "stderr": asyncio.subprocess.PIPE,
                    "limit": self.config.max_message_bytes + 1,
                }
                if os.name == "nt":
                    process_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    process_kwargs["start_new_session"] = True
                try:
                    process = await asyncio.create_subprocess_exec(
                        str(runner), "--protocol", RPC_PROTOCOL, **process_kwargs
                    )
                except (OSError, ValueError) as exc:
                    raise PluginRunnerError(
                        "runner_start_failed", "plugin runner could not be started", boundary=boundary
                    ) from exc
                assert process.stdin is not None
                assert process.stdout is not None
                assert process.stderr is not None
                exchange = self._exchange(
                    process,
                    operation_id,
                    dict(input_data or {}),
                    declared,
                    granted,
                    host_port_handler,
                    boundary,
                )
                try:
                    result, events, state, host_calls = await asyncio.wait_for(
                        exchange, timeout=self.config.timeout_seconds
                    )
                except asyncio.TimeoutError as exc:
                    raise PluginRunnerError(
                        "runner_timeout",
                        "plugin runner exceeded its hard timeout",
                        boundary=boundary,
                    ) from exc
                if process.returncode is None:
                    await process.wait()
                if process.returncode != 0:
                    raise PluginRunnerError(
                        "runner_failed",
                        "plugin runner exited unsuccessfully",
                        details={
                            "exit_code": process.returncode,
                            "stderr": bytes(state.stderr).decode("utf-8", errors="replace"),
                        },
                        boundary=boundary,
                    )
                return PluginRunResult(
                    result=result,
                    events=tuple(events),
                    stderr=bytes(state.stderr).decode("utf-8", errors="replace"),
                    exit_code=int(process.returncode or 0),
                    host_call_count=host_calls,
                    elapsed_seconds=round(time.monotonic() - started, 3),
                    execution_boundary=boundary,
                )
        except asyncio.CancelledError:
            if process is not None:
                await _terminate_process_group(process)
            raise
        except Exception:
            if process is not None:
                await _terminate_process_group(process)
            raise
        finally:
            if process is not None:
                await _terminate_process_group(process)

    async def _exchange(
        self,
        process: asyncio.subprocess.Process,
        operation_id: str,
        input_data: dict[str, Any],
        declared: set[str],
        granted: set[str],
        host_port_handler: HostPortHandler | None,
        boundary: dict[str, Any],
    ) -> tuple[Any, list[dict[str, Any]], _OutputState, int]:
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        state = _OutputState(self.config.max_output_bytes)
        stdout_task = asyncio.create_task(
            _pump_stdout(process.stdout, queue, state, self.config.max_message_bytes)
        )
        stderr_task = asyncio.create_task(_pump_stderr(process.stderr, queue, state))
        events: list[dict[str, Any]] = []
        host_calls = 0
        final_result: Any = None
        received_final = False
        await _send_message(
            process.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "plugin.run",
                "params": {
                    "protocol": RPC_PROTOCOL,
                    "operation_id": operation_id,
                    "input": input_data,
                    "execution_boundary": dict(boundary),
                },
            },
            self.config.max_message_bytes,
        )
        try:
            while not received_final:
                kind, value = await queue.get()
                if kind in {"stderr_eof"}:
                    continue
                if kind == "error":
                    if isinstance(value, PluginRunnerError):
                        value.boundary.update(boundary)
                        raise value
                    raise PluginRunnerError(
                        "runner_io_failed", "plugin runner I/O failed", boundary=boundary
                    ) from value
                if kind == "stdout_eof":
                    raise PluginRunnerError(
                        "runner_protocol_incomplete",
                        "plugin runner exited without a final response",
                        boundary=boundary,
                    )
                try:
                    message = json.loads(value.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise PluginRunnerError(
                        "invalid_rpc", "plugin runner emitted invalid JSON-RPC", boundary=boundary
                    ) from exc
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise PluginRunnerError(
                        "invalid_rpc", "plugin runner emitted an invalid JSON-RPC envelope", boundary=boundary
                    )
                if "method" in message:
                    method = message.get("method")
                    if method == "run.event" and "id" not in message:
                        params = message.get("params")
                        if not isinstance(params, dict) or not isinstance(params.get("type"), str):
                            raise PluginRunnerError(
                                "invalid_rpc", "plugin run event is invalid", boundary=boundary
                            )
                        events.append(dict(params))
                        continue
                    if method != "host.call" or "id" not in message:
                        raise PluginRunnerError(
                            "rpc_method_forbidden", "plugin runner requested an unsupported RPC method", boundary=boundary
                        )
                    host_calls += 1
                    if host_calls > self.config.max_host_calls:
                        raise PluginRunnerError(
                            "host_call_limit_exceeded", "plugin runner exceeded Host Port call budget", boundary=boundary
                        )
                    await self._handle_host_call(
                        process.stdin,
                        message,
                        declared,
                        granted,
                        host_port_handler,
                    )
                    continue
                if message.get("id") != 1 or ("result" in message) == ("error" in message):
                    raise PluginRunnerError(
                        "invalid_rpc", "plugin runner response does not match the active request", boundary=boundary
                    )
                if "error" in message:
                    error = message["error"]
                    raise PluginRunnerError(
                        "plugin_operation_failed",
                        str(error.get("message", "plugin operation failed")) if isinstance(error, dict) else "plugin operation failed",
                        details={"plugin_error": error},
                        boundary=boundary,
                    )
                final_result = message["result"]
                received_final = True

            process.stdin.close()
            # A runner may have spawned same-group children which inherited the
            # RPC pipes.  Give the leader a brief chance to exit after its final
            # response, then clean the entire group before waiting for EOF.
            for _ in range(10):
                if process.returncode is not None:
                    break
                await asyncio.sleep(0.005)
            await _terminate_process_group(process)
            await process.wait()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            while not queue.empty():
                kind, value = queue.get_nowait()
                if kind == "error":
                    if isinstance(value, PluginRunnerError):
                        value.boundary.update(boundary)
                        raise value
                    raise PluginRunnerError(
                        "runner_io_failed", "plugin runner I/O failed", boundary=boundary
                    ) from value
                if kind == "stdout":
                    raise PluginRunnerError(
                        "multiple_rpc_results", "plugin runner emitted output after its final response", boundary=boundary
                    )
            return final_result, events, state, host_calls
        finally:
            if not stdout_task.done():
                stdout_task.cancel()
            if not stderr_task.done():
                stderr_task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

    async def _handle_host_call(
        self,
        writer: asyncio.StreamWriter | Any,
        message: Mapping[str, Any],
        declared: set[str],
        granted: set[str],
        handler: HostPortHandler | None,
    ) -> None:
        identifier = message.get("id")
        params = message.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("port"), str):
            await _send_message(
                writer,
                _rpc_error(identifier, -32602, "host.call requires port and input"),
                self.config.max_message_bytes,
            )
            return
        port = params["port"]
        raw_input = params.get("input", {})
        if not isinstance(raw_input, dict):
            await _send_message(
                writer,
                _rpc_error(identifier, -32602, "Host Port input must be an object"),
                self.config.max_message_bytes,
            )
            return
        if port not in declared or port not in granted:
            await _send_message(
                writer,
                _rpc_error(identifier, -32003, "Host Port is not declared and granted"),
                self.config.max_message_bytes,
            )
            return
        if handler is None:
            await _send_message(
                writer,
                _rpc_error(identifier, -32601, "Host Port handler is unavailable"),
                self.config.max_message_bytes,
            )
            return
        try:
            result = handler(port, dict(raw_input))
            if inspect.isawaitable(result):
                result = await result
            response: dict[str, Any] = {"jsonrpc": "2.0", "id": identifier, "result": result}
            await _send_message(writer, response, self.config.max_message_bytes)
        except PluginRunnerError:
            raise
        except Exception as exc:
            await _send_message(
                writer,
                _rpc_error(
                    identifier,
                    -32010,
                    "Host Port call failed",
                    {"type": type(exc).__name__},
                ),
                self.config.max_message_bytes,
            )


__all__ = [
    "EXECUTION_BOUNDARY",
    "PluginProcessBroker",
    "PluginRunResult",
    "PluginRunnerConfig",
    "PluginRunnerError",
    "RPC_PROTOCOL",
    "sanitized_plugin_environment",
]
