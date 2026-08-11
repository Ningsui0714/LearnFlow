from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import time
from typing import Any

from app.services.workspace_files import WorkspaceError, read_workspace_file, resolve_workspace_path


RUN_TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 256 * 1024
SYNTAX_PROGRAM = (
    "import ast,pathlib,sys; "
    "p=pathlib.Path(sys.argv[1]); "
    "ast.parse(p.read_text(encoding='utf-8'), filename=str(p))"
)


def _is_reparse(path: Path) -> bool:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return False
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(flag and getattr(info, "st_file_attributes", 0) & flag)


def validate_interpreter(raw_path: str) -> dict[str, str]:
    if not raw_path or "\x00" in raw_path:
        raise WorkspaceError(400, "Python 解释器路径无效", "invalid_interpreter")
    path = Path(raw_path).expanduser()
    if not path.is_absolute() or not path.exists() or not path.is_file():
        raise WorkspaceError(400, "请选择真实存在的本地 Python 解释器", "invalid_interpreter")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or _is_reparse(resolved):
        raise WorkspaceError(400, "Python 解释器目标无效", "unsafe_interpreter")
    try:
        completed = subprocess.run(
            [str(resolved), "--version"],
            cwd=str(resolved.parent),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=5,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkspaceError(400, "无法启动所选 Python 解释器", "interpreter_unavailable") from exc
    version = (completed.stdout or completed.stderr).decode("utf-8", errors="replace").strip()
    if completed.returncode != 0 or "Python" not in version:
        raise WorkspaceError(400, "所选程序不是可用的 Python 解释器", "invalid_interpreter")
    return {"interpreter_path": str(resolved), "version": version[:160]}


def runtime_plan(
    root: Path,
    *,
    interpreter_path: str,
    script_path: str,
    mode: str,
    args: list[str],
    actor: str,
) -> dict[str, Any]:
    if mode not in {"syntax", "run"} or actor not in {"user", "agent"}:
        raise WorkspaceError(400, "运行计划参数无效", "invalid_run_plan")
    interpreter = validate_interpreter(interpreter_path)
    relative, script = resolve_workspace_path(root, script_path, actor=actor)
    if not script.is_file() or script.suffix.casefold() != ".py":
        raise WorkspaceError(400, "本地 Python 运行只接受工作区内的 .py 文件", "python_file_required")
    if read_workspace_file(root, relative, actor=actor)["kind"] != "workspace_text":
        raise WorkspaceError(400, "Python 文件必须是 2 MB 内的 UTF-8 文本", "python_text_required")
    if len(args) > 32:
        raise WorkspaceError(400, "运行参数不能超过 32 个", "invalid_run_argument")
    safe_args: list[str] = []
    for value in args:
        if not isinstance(value, str) or "\x00" in value or len(value) > 1024:
            raise WorkspaceError(400, "运行参数无效", "invalid_run_argument")
        safe_args.append(value)
    command = (
        [interpreter["interpreter_path"], "-c", SYNTAX_PROGRAM, str(script)]
        if mode == "syntax"
        else [interpreter["interpreter_path"], str(script), *safe_args]
    )
    return {
        "mode": mode,
        "actor": actor,
        "interpreter": interpreter,
        "script": relative,
        "script_absolute": str(script),
        "working_directory": str(root),
        "args": safe_args,
        "command": command,
        "execution_boundary": "trusted_local_execution",
    }


def execute_runtime_plan(plan: dict[str, Any]) -> dict[str, Any]:
    working_directory = str(plan.get("working_directory") or "")
    interpreter = plan.get("interpreter") or {}
    if not working_directory or not isinstance(interpreter, dict):
        raise WorkspaceError(400, "运行计划不完整", "invalid_run_plan")
    # A proposal can wait for user confirmation. Re-resolve the interpreter and
    # script immediately before spawning so a file cannot be swapped for a
    # symlink/reparse point between proposal and confirmation.
    fresh_plan = runtime_plan(
        Path(working_directory),
        interpreter_path=str(interpreter.get("interpreter_path") or ""),
        script_path=str(plan.get("script") or ""),
        mode=str(plan.get("mode") or ""),
        args=list(plan.get("args") or []),
        actor=str(plan.get("actor") or "user"),
    )
    command = list(fresh_plan["command"])
    working_directory = str(fresh_plan["working_directory"])
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=working_directory,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=RUN_TIMEOUT_SECONDS,
            check=False,
            shell=False,
            env=env,
        )
        timed_out = False
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = None
        stdout = exc.stdout or b""
        stderr = (exc.stderr or b"") + b"\nExecution timed out."
    except OSError as exc:
        raise WorkspaceError(500, "无法启动本地 Python 进程", "runtime_start_failed") from exc
    return {
        "mode": fresh_plan.get("mode"),
        "interpreter": fresh_plan.get("interpreter"),
        "script": fresh_plan.get("script"),
        "working_directory": working_directory,
        "args": list(fresh_plan.get("args") or []),
        "exit_code": return_code,
        "timed_out": timed_out,
        "passed": return_code == 0 and not timed_out,
        "stdout": stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        "stderr": stderr[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        "elapsed": round(time.monotonic() - started, 4),
        "output_truncated": len(stdout) > MAX_OUTPUT_BYTES or len(stderr) > MAX_OUTPUT_BYTES,
        "execution_boundary": "trusted_local_execution",
    }
