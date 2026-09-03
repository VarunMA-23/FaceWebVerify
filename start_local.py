#!/usr/bin/env python3
"""Start backend and frontend dev servers using ports from .env."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8004"))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "3004"))
BACKEND_URL = os.environ.get("BACKEND_URL", f"http://127.0.0.1:{BACKEND_PORT}")


def _write_frontend_config() -> None:
    config_path = ROOT / "frontend" / "config.local.js"
    config_path.write_text(f"window.__API_BASE__ = '{BACKEND_URL}';\n", encoding="utf-8")


def main() -> int:
    _write_frontend_config()

    env = os.environ.copy()
    env["SERVE_FRONTEND"] = "false"

    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--reload",
            "--host",
            "127.0.0.1",
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=ROOT,
        env=env,
    )
    frontend = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(FRONTEND_PORT), "--bind", "127.0.0.1"],
        cwd=ROOT / "frontend",
    )

    print(f"Backend:  {BACKEND_URL}  (docs: {BACKEND_URL}/docs)")
    print(f"Frontend: http://127.0.0.1:{FRONTEND_PORT}/")
    print("Press Ctrl+C to stop both servers.")

    def shutdown(_signum: int, _frame: object) -> None:
        backend.terminate()
        frontend.terminate()
        backend.wait(timeout=5)
        frontend.wait(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    return backend.wait()


if __name__ == "__main__":
    raise SystemExit(main())
