"""Run Django ASGI plus the PostgreSQL worker in one Render Free service."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from taskiller.core.config import get_settings

ROOT = Path(__file__).resolve().parents[1]


def _spawn(args: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(args, cwd=ROOT)


def main() -> None:
    migrate = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "django_cutover_migrate.py"),
        ],
        cwd=ROOT,
        check=False,
    )
    if migrate.returncode != 0:
        raise SystemExit(migrate.returncode)

    bootstrap = subprocess.run(
        [
            sys.executable,
            str(ROOT / "manage.py"),
            "bootstrap_taskiller_admin",
            "--if-configured",
        ],
        cwd=ROOT,
        check=False,
    )
    if bootstrap.returncode != 0:
        raise SystemExit(bootstrap.returncode)

    settings = get_settings()
    children: list[subprocess.Popen[bytes]] = []

    try:
        if settings.embedded_worker_enabled:
            children.append(
                _spawn(
                    [
                        sys.executable,
                        str(ROOT / "manage.py"),
                        "taskiller_worker",
                    ]
                )
            )

        port = os.environ.get("PORT", "8000")
        api = _spawn(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "taskiller.django_project.asgi:application",
                "--app-dir",
                "src",
                "--host",
                "0.0.0.0",
                "--port",
                port,
                "--proxy-headers",
                "--no-access-log",
            ]
        )
        children.append(api)

        def stop(signum: int, _frame: object) -> None:
            for child in children:
                if child.poll() is None:
                    child.send_signal(signum)

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        while True:
            for child in children:
                code = child.poll()
                if code is not None:
                    # A clean worker exit is still a service failure.
                    raise SystemExit(code if child is api else (code or 1))
            time.sleep(0.25)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
