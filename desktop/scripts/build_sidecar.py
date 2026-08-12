"""Build the FastAPI sidecar with the target-triple name required by Tauri."""

from __future__ import annotations

from pathlib import Path
import platform
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_ROOT = REPO_ROOT / "desktop"
BACKEND_ROOT = REPO_ROOT / "backend"
BUILD_ROOT = DESKTOP_ROOT / ".sidecar-build"
BINARIES_ROOT = DESKTOP_ROOT / "src-tauri" / "binaries"


def rust_host_triple() -> str:
    output = subprocess.check_output(["rustc", "-vV"], text=True)
    for line in output.splitlines():
        if line.startswith("host: "):
            return line.removeprefix("host: ").strip()
    raise RuntimeError("rustc did not report a host target triple")


def main() -> None:
    target = rust_host_triple()
    executable = "learnflow-backend.exe" if platform.system() == "Windows" else "learnflow-backend"
    subprocess.run([
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "learnflow-backend",
        "--paths",
        str(BACKEND_ROOT),
        "--distpath",
        str(BUILD_ROOT / "dist"),
        "--workpath",
        str(BUILD_ROOT / "work"),
        "--specpath",
        str(BUILD_ROOT),
        # SQLAlchemy loads the aiosqlite driver dynamically, so PyInstaller
        # cannot discover it from the import graph on its own.
        "--hidden-import=aiosqlite",
        str(BACKEND_ROOT / "desktop_entry.py"),
    ], check=True, cwd=REPO_ROOT)
    BINARIES_ROOT.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if platform.system() == "Windows" else ""
    destination = BINARIES_ROOT / f"learnflow-backend-{target}{suffix}"
    shutil.copy2(BUILD_ROOT / "dist" / executable, destination)
    print(destination)


if __name__ == "__main__":
    main()
