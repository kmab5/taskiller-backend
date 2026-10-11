"""Regression for DRF authentication/exception-handler import ordering."""

import os
import subprocess
import sys


def test_drf_auth_and_exception_handler_import_in_fresh_interpreter() -> None:
    env = os.environ.copy()
    env.setdefault("DJANGO_SETTINGS_MODULE", "taskiller.django_project.settings")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import django; django.setup(); "
                "from rest_framework.views import APIView; "
                "from taskiller.django_api.authentication import TaskillerBearerAuthentication; "
                "from taskiller.django_api.errors import taskiller_exception_handler; "
                "assert APIView and TaskillerBearerAuthentication and taskiller_exception_handler"
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
