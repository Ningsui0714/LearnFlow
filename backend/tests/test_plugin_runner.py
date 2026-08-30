import asyncio
import os
from pathlib import Path
import textwrap
import time

import pytest

from app.services.plugin_runner import (
    PluginProcessBroker,
    PluginRunnerConfig,
    PluginRunnerError,
    RPC_PROTOCOL,
    sanitized_plugin_environment,
)


def write_runner(tmp_path, body: str):
    path = tmp_path / "runner"
    path.write_text(
        "#!/usr/bin/env python3\n" + textwrap.dedent(body),
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def enabled_config(**overrides):
    values = {
        "execution_mode": "trusted_signed_process",
        "timeout_seconds": 2,
        "max_message_bytes": 16 * 1024,
        "max_output_bytes": 64 * 1024,
        "max_host_calls": 4,
    }
    values.update(overrides)
    return PluginRunnerConfig(**values)


def test_runner_uses_fixed_rpc_envelope_clean_environment_and_host_port(tmp_path, monkeypatch):
    runner = write_runner(
        tmp_path,
        r'''
        import json, os, sys

        request = json.loads(sys.stdin.readline())
        assert sys.argv[1:] == ["--protocol", "learnflow.plugin-rpc.v1"]
        assert request["method"] == "plugin.run"
        print(json.dumps({
            "jsonrpc": "2.0", "id": "call-1", "method": "host.call",
            "params": {"port": "project.read.v1", "input": {"project_id": 7}}
        }), flush=True)
        host_response = json.loads(sys.stdin.readline())
        print(json.dumps({
            "jsonrpc": "2.0", "method": "run.event",
            "params": {"type": "source_pinned", "payload": {"count": 1}}
        }), flush=True)
        print(json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "result": {
                "operation_id": request["params"]["operation_id"],
                "input": request["params"]["input"],
                "project": host_response["result"],
                "has_llm_secret": "LLM_API_KEY" in os.environ,
                "boundary": request["params"]["execution_boundary"]
            }
        }), flush=True)
        ''',
    )
    monkeypatch.setenv("LLM_API_KEY", "must-not-leak")
    captured = []

    async def host_call(port, payload):
        captured.append((port, payload))
        return {"id": payload["project_id"], "name": "Safe project"}

    result = asyncio.run(
        PluginProcessBroker(enabled_config()).run(
            runner,
            "generate",
            {"role_title": "Agent 工程师"},
            declared_host_ports=["project.read.v1"],
            granted_host_ports=["project.read.v1"],
            host_port_handler=host_call,
            trust_state="trusted_signed",
        )
    )

    assert captured == [("project.read.v1", {"project_id": 7})]
    assert result.result["operation_id"] == "generate"
    assert result.result["project"]["id"] == 7
    assert result.result["has_llm_secret"] is False
    assert result.events == ({"type": "source_pinned", "payload": {"count": 1}},)
    assert result.host_call_count == 1
    assert result.execution_boundary["filesystem_isolation"] is False
    assert result.execution_boundary["network_isolation"] is False
    assert result.execution_boundary["secrets_isolation"] is False
    assert result.execution_boundary["cpu_isolation"] is False
    assert result.execution_boundary["memory_isolation"] is False
    assert result.execution_boundary["execution_mode"] == "trusted_signed_process"


def test_undeclared_or_ungranted_host_port_never_reaches_handler(tmp_path):
    runner = write_runner(
        tmp_path,
        r'''
        import json, sys
        json.loads(sys.stdin.readline())
        print(json.dumps({
            "jsonrpc": "2.0", "id": "call-1", "method": "host.call",
            "params": {"port": "source.read.v1", "input": {}}
        }), flush=True)
        denied = json.loads(sys.stdin.readline())
        print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": denied["error"]}), flush=True)
        ''',
    )

    def forbidden_handler(_port, _payload):
        raise AssertionError("unauthorized Host Port reached handler")

    result = asyncio.run(
        PluginProcessBroker(enabled_config()).run(
            runner,
            "explain",
            declared_host_ports=["source.read.v1"],
            granted_host_ports=[],
            host_port_handler=forbidden_handler,
            trust_state="trusted_signed",
        )
    )
    assert result.result["code"] == -32003


def test_execution_is_disabled_by_default_and_unsigned_dev_is_separate_opt_in(tmp_path):
    with pytest.raises(PluginRunnerError) as caught:
        asyncio.run(PluginProcessBroker().run(tmp_path / "missing", "generate"))
    assert caught.value.code == "plugin_execution_disabled"

    runner = write_runner(
        tmp_path,
        r'''
        import json, sys
        json.loads(sys.stdin.readline())
        print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}), flush=True)
        ''',
    )
    with pytest.raises(PluginRunnerError) as caught:
        asyncio.run(
            PluginProcessBroker(enabled_config()).run(
                runner, "generate", trust_state="untrusted_development"
            )
        )
    assert caught.value.code == "plugin_release_not_trusted"

    config = enabled_config(allow_unsigned_development=True, environment="development")
    result = asyncio.run(
        PluginProcessBroker(config).run(
            runner, "generate", trust_state="untrusted_development"
        )
    )
    assert result.result == {"ok": True}


def test_runner_timeout_terminates_process_group(tmp_path):
    runner = write_runner(
        tmp_path,
        r'''
        import sys, time
        sys.stdin.readline()
        time.sleep(30)
        ''',
    )
    started = time.monotonic()
    with pytest.raises(PluginRunnerError) as caught:
        asyncio.run(
            PluginProcessBroker(enabled_config(timeout_seconds=0.1)).run(
                runner, "generate", trust_state="trusted_signed"
            )
        )
    assert caught.value.code == "runner_timeout"
    assert time.monotonic() - started < 3


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group assertion")
def test_runner_cleans_descendants_after_successful_response(tmp_path):
    pid_file = tmp_path / "child.pid"
    runner = write_runner(
        tmp_path,
        r'''
        import json, pathlib, subprocess, sys
        request = json.loads(sys.stdin.readline())
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        pathlib.Path(request["params"]["input"]["pid_file"]).write_text(str(child.pid))
        print(json.dumps({"jsonrpc":"2.0","id":1,"result":{"ok":True}}), flush=True)
        ''',
    )
    result = asyncio.run(
        PluginProcessBroker(enabled_config()).run(
            runner,
            "generate",
            {"pid_file": str(pid_file)},
            trust_state="trusted_signed",
        )
    )
    assert result.result == {"ok": True}
    child_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail("plugin descendant survived broker cleanup")


def test_runner_enforces_per_message_and_total_output_limits(tmp_path):
    oversized = write_runner(
        tmp_path,
        r'''
        import json, sys
        sys.stdin.readline()
        print(json.dumps({"jsonrpc":"2.0","method":"run.event","params":{"type":"x" * 3000}}), flush=True)
        ''',
    )
    with pytest.raises(PluginRunnerError) as caught:
        asyncio.run(
            PluginProcessBroker(
                enabled_config(max_message_bytes=1024, max_output_bytes=64 * 1024)
            ).run(oversized, "generate", trust_state="trusted_signed")
        )
    assert caught.value.code == "rpc_message_too_large"

    noisy = write_runner(
        tmp_path,
        r'''
        import json, sys
        sys.stdin.readline()
        for index in range(30):
            print(json.dumps({
                "jsonrpc":"2.0", "method":"run.event",
                "params":{"type":"noise", "payload":{"text":"x" * 400, "i": index}}
            }), flush=True)
        ''',
    )
    with pytest.raises(PluginRunnerError) as caught:
        asyncio.run(
            PluginProcessBroker(
                enabled_config(max_message_bytes=1024, max_output_bytes=4096)
            ).run(noisy, "generate", trust_state="trusted_signed")
        )
    assert caught.value.code == "runner_output_limited"


def test_runner_enforces_host_call_budget(tmp_path):
    runner = write_runner(
        tmp_path,
        r'''
        import json, sys
        json.loads(sys.stdin.readline())
        for index in range(2):
            print(json.dumps({
                "jsonrpc":"2.0", "id":f"call-{index}", "method":"host.call",
                "params":{"port":"project.read.v1", "input":{}}
            }), flush=True)
            json.loads(sys.stdin.readline())
        ''',
    )
    with pytest.raises(PluginRunnerError) as caught:
        asyncio.run(
            PluginProcessBroker(enabled_config(max_host_calls=1)).run(
                runner,
                "generate",
                declared_host_ports=["project.read.v1"],
                granted_host_ports=["project.read.v1"],
                host_port_handler=lambda _port, _input: {},
                trust_state="trusted_signed",
            )
        )
    assert caught.value.code == "host_call_limit_exceeded"


@pytest.mark.parametrize(
    ("body", "error_code"),
    [
        (
            '''
            import sys
            sys.stdin.readline()
            print("not-json", flush=True)
            ''',
            "invalid_rpc",
        ),
        (
            '''
            import json, sys
            sys.stdin.readline()
            print(json.dumps({"jsonrpc":"2.0","id":1,"result":{"first":True}}), flush=True)
            print(json.dumps({"jsonrpc":"2.0","id":1,"result":{"second":True}}), flush=True)
            ''',
            "multiple_rpc_results",
        ),
        (
            '''
            import sys
            sys.stdin.readline()
            sys.stderr.write("runner failed intentionally")
            raise SystemExit(7)
            ''',
            "runner_protocol_incomplete",
        ),
    ],
)
def test_runner_rejects_malformed_duplicate_and_crashing_protocols(tmp_path, body, error_code):
    runner = write_runner(tmp_path, body)
    with pytest.raises(PluginRunnerError) as caught:
        asyncio.run(
            PluginProcessBroker(enabled_config()).run(
                runner,
                "generate",
                trust_state="trusted_signed",
            )
        )
    assert caught.value.code == error_code


def test_official_role_runner_preserves_multi_source_provenance_and_configuration():
    repository = Path(__file__).resolve().parents[2]
    runner = repository / "plugins/role_capability_graph/bin/darwin-arm64/runner"
    if not runner.exists():
        pytest.skip("official source runner is not available")

    async def host_call(port, _payload):
        if port == "project.read.v1":
            return {"id": 7, "name": "岗位图谱", "description": "测试来源映射"}
        if port == "source.read.v1":
            return {
                "sources": [
                    {
                        "ref": "source:11@v2",
                        "source_id": 11,
                        "source_version_id": 102,
                        "content_hash": "1" * 64,
                        "authority_tier": "official",
                        "status": "ready",
                        "chunks": [{"content": "设计 Agent 工具协议与权限边界。"}],
                    },
                    {
                        "ref": "source:12@v4",
                        "source_id": 12,
                        "source_version_id": 204,
                        "content_hash": "2" * 64,
                        "authority_tier": "learner_owned",
                        "status": "ready",
                        "chunks": [{"content": "验证离线评测集与失败样本。"}],
                    },
                ]
            }
        raise AssertionError(port)

    result = asyncio.run(
        PluginProcessBroker(enabled_config()).run(
            runner,
            "generate",
            {
                "role_title": "Agent 工程师",
                "role_summary": "构建可靠智能应用",
                "source_ids": [11, 12],
                "plugin_configuration": {"max_tasks": 2, "include_process_view": False},
            },
            declared_host_ports=["project.read.v1", "source.read.v1"],
            granted_host_ports=["project.read.v1", "source.read.v1"],
            host_port_handler=host_call,
            trust_state="trusted_signed",
        )
    )
    snapshot = result.result["snapshot"]
    tasks = [
        item for item in snapshot["components"]["semantic-graph"]["nodes"]
        if item["type"] == "task"
    ]
    assert len(tasks) == 2
    assert tasks[0]["evidence_refs"] == ["source:11@v2"]
    assert tasks[1]["evidence_refs"] == ["source:12@v4"]
    assert all(
        item.get("id") != "process-bridge"
        for item in snapshot["components"]["views"]["views"]
    )


def test_cancellation_cleans_up_runner(tmp_path):
    runner = write_runner(
        tmp_path,
        r'''
        import sys, time
        sys.stdin.readline()
        time.sleep(30)
        ''',
    )

    async def scenario():
        task = asyncio.create_task(
            PluginProcessBroker(enabled_config(timeout_seconds=10)).run(
                runner, "generate", trust_state="trusted_signed"
            )
        )
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    started = time.monotonic()
    asyncio.run(scenario())
    assert time.monotonic() - started < 3


def test_sanitized_environment_never_inherits_common_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://secret")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    environment = sanitized_plugin_environment(tmp_path)
    assert "DATABASE_URL" not in environment
    assert "LLM_API_KEY" not in environment
    assert "OPENAI_API_KEY" not in environment
    assert environment["HOME"] == str(tmp_path.resolve())
    assert RPC_PROTOCOL == "learnflow.plugin-rpc.v1"
