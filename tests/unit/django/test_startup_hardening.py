from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def migration_module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "django_cutover_migrate.py"
    spec = importlib.util.spec_from_file_location("audit_migration_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_failure_releases_startup_lock():
    module = migration_module()
    database = MagicMock()
    atomic = MagicMock()
    cursor = database.cursor.return_value.__enter__.return_value
    with (
        patch.object(module, "connection", database),
        patch.object(module.transaction, "atomic", return_value=atomic),
        patch.object(module, "_domain_adopted", return_value=True),
        patch.object(module, "call_command", side_effect=RuntimeError("migration failed")),
        pytest.raises(RuntimeError, match="migration failed"),
    ):
        module.main()
    sql = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("pg_advisory_xact_lock(" in statement for statement in sql)
    assert atomic.__exit__.call_args.args[0] is RuntimeError


def test_asgi_connections_do_not_persist_per_request_threads():
    from django.conf import settings

    assert settings.DATABASES["default"]["CONN_MAX_AGE"] == 0


def test_json_error_logs_exclude_request_objects_with_signed_query_strings():
    from django.test import RequestFactory

    from taskiller.core.logging import JsonFormatter

    record = logging.LogRecord("django.request", logging.WARNING, "", 0, "Forbidden", (), None)
    record.request = RequestFactory().get("/download?token=secret-download-credential")
    assert "secret-download-credential" not in JsonFormatter().format(record)
