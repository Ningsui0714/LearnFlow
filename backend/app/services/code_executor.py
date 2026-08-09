"""
Code execution sandbox.

Runs Python code in a subprocess with resource limits.
"""
import subprocess
import tempfile
import os
import signal
import time
from typing import Dict, Optional


MAX_EXECUTION_TIME = 10  # seconds
MAX_OUTPUT_SIZE = 100 * 1024  # 100KB


def _python_binary() -> str:
    """Prefer the project-mode runtime venv python (has torch etc.),
    fall back to system python3."""
    try:
        from app.services.project_runner import venv_dir
        py = os.path.join(venv_dir(), "bin", "python")
        if os.path.isfile(py):
            return py
    except Exception:
        pass
    return "python3"


def execute_code(
    code: str,
    test_input: str = "",
    timeout: int = MAX_EXECUTION_TIME,
) -> Dict:
    """
    Execute Python code in a subprocess sandbox.

    Returns:
        {"stdout": str, "stderr": str, "exit_code": int, "timed_out": bool}
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        fpath = f.name

    try:
        start = time.time()
        process = subprocess.Popen(
            [_python_binary(), fpath],
            stdin=subprocess.PIPE if test_input else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=lambda: signal.alarm(timeout + 1)
            if hasattr(signal, "alarm")
            else None,
        )

        try:
            stdout, stderr = process.communicate(
                input=test_input if test_input else None,
                timeout=timeout,
            )
            timed_out = False
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            timed_out = True

        elapsed = time.time() - start

        # Truncate output
        if len(stdout) > MAX_OUTPUT_SIZE:
            stdout = stdout[:MAX_OUTPUT_SIZE] + "\n... (输出截断)"
        if len(stderr) > MAX_OUTPUT_SIZE:
            stderr = stderr[:MAX_OUTPUT_SIZE] + "\n... (输出截断)"

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": process.returncode,
            "timed_out": timed_out,
            "elapsed": round(elapsed, 2),
        }

    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"执行错误: {str(e)}",
            "exit_code": -1,
            "timed_out": False,
            "elapsed": 0,
        }
    finally:
        try:
            os.unlink(fpath)
        except OSError:
            pass
