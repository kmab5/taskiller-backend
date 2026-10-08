from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured

from taskiller import __version__

BASE_DIR = Path(__file__).resolve().parents[3]
TASKILLER_ENV = os.getenv("TASKILLER_ENV", "local").casefold()


def _json_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ImproperlyConfigured(f"{name} must be a JSON array of strings") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ImproperlyConfigured(f"{name} must be a JSON array of strings")
    return value


def _database_config() -> dict[str, object]:
    raw = os.getenv(
        "TASKILLER_DATABASE_URL",
        "postgresql+psycopg://taskiller:taskiller@localhost:5432/taskiller",
    )
    normalized = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlsplit(normalized)

    if parsed.scheme not in {"postgresql", "postgres"}:
        raise ImproperlyConfigured("TASKILLER_DATABASE_URL must be a PostgreSQL URL for Django")
    if not parsed.hostname:
        raise ImproperlyConfigured("TASKILLER_DATABASE_URL must include a database host")

    options = dict(parse_qsl(parsed.query, keep_blank_values=True))
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")) or "taskiller",
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": options,
    }


SECRET_KEY = os.getenv("TASKILLER_DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if TASKILLER_ENV == "production":
        raise ImproperlyConfigured(
            "TASKILLER_DJANGO_SECRET_KEY is required before Django is production-facing"
        )
    SECRET_KEY = "taskiller-django-migration-local-only-secret"

DEBUG = TASKILLER_ENV == "local"

ALLOWED_HOSTS = _json_list(
    "TASKILLER_ALLOWED_HOSTS",
    ["localhost", "127.0.0.1", "testserver"],
)

_cors_origins = _json_list(
    "TASKILLER_CORS_ORIGINS",
    ["http://localhost:3000"],
)
CSRF_TRUSTED_ORIGINS = [
    origin
    for origin in _cors_origins
    if origin.startswith("http://") or origin.startswith("https://")
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "taskiller.django_domain.apps.TaskillerDomainConfig",
    "taskiller.django_operations",
]

MIDDLEWARE = [
    "taskiller.django_api.middleware.TaskillerRuntimeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "taskiller.django_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "taskiller.django_project.wsgi.application"
ASGI_APPLICATION = "taskiller.django_project.asgi.application"

DATABASES = {"default": _database_config()}

# Phase 2: existing Taskiller tables are still owned by Alembic. This router is
# a second safety layer in addition to every domain model using managed=False.
# The bridge app deliberately has no Django migration module yet. Its schema
# baseline is the checked model/introspection manifest, not DDL ownership.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": ("django.contrib.auth.password_validation.UserAttributeSimilarityValidator")},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_SECURE = TASKILLER_ENV == "production"
CSRF_COOKIE_SECURE = TASKILLER_ENV == "production"
SESSION_COOKIE_HTTPONLY = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "taskiller.django_api.authentication.TaskillerBearerAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "taskiller.django_api.errors.taskiller_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Taskiller API",
    "DESCRIPTION": (
        "Parallel Django/DRF migration foundation. FastAPI remains canonical "
        "until the API phases preserve the existing v1 contract."
    ),
    "VERSION": __version__,
    "SERVE_INCLUDE_SCHEMA": False,
}
