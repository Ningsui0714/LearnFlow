"""Packaged FastAPI sidecar entry point for the Tauri desktop application."""

from __future__ import annotations

import argparse
import multiprocessing
import os

import uvicorn

from app.main import app


def main() -> None:
    parser = argparse.ArgumentParser(description="LearnFlow desktop API sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("desktop sidecar may only bind a loopback address")
    if os.getenv("DESKTOP_MODE", "").lower() != "true":
        parser.error("DESKTOP_MODE=true is required")
    if not os.getenv("DESKTOP_TOKEN"):
        parser.error("DESKTOP_TOKEN is required")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=os.getenv("LEARNFLOW_LOG_LEVEL", "info"),
        access_log=False,
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
