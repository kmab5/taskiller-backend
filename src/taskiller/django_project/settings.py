from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from taskiller import __version__

BASE_DIR = Path(__file__).resolve().parents[3]
load_dotenv(BASE_DIR / ".env", override=False)
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
        # ASGI threads must not retain one connection each; Neon pools upstream.
        "CONN_MAX_AGE": 0,
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

# Django migrations own both the domain schema and built-in admin/auth tables.
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

DATA_UPLOAD_MAX_MEMORY_SIZE = 16 * 1024 * 1024

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
    "DESCRIPTION": "Taskiller's Django REST API. The client contract is /openapi.json.",
    "VERSION": __version__,
    "SERVE_INCLUDE_SCHEMA": False,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "taskiller.core.logging.JsonFormatter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
    },
    "root": {"handlers": ["console"], "level": os.getenv("TASKILLER_LOG_LEVEL", "INFO")},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.server": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}


# Staff console is isolated from product JWTs, refresh cookies and CORS.
ADMIN_CONSOLE_ENABLED = os.getenv("TASKILLER_ADMIN_CONSOLE_ENABLED", "false").lower() == "true"
ADMIN_CONSOLE_WRITES_ENABLED = (
    os.getenv("TASKILLER_ADMIN_CONSOLE_WRITES_ENABLED", "false").lower() == "true"
)
ADMIN_CONSOLE_ORIGINS = _json_list("TASKILLER_ADMIN_CONSOLE_ORIGINS", [])
ADMIN_CONSOLE_ENCRYPTION_KEYS = [
    value.strip()
    for value in os.getenv("TASKILLER_ADMIN_CONSOLE_ENCRYPTION_KEYS", "").split(",")
    if value.strip()
]
ADMIN_CONSOLE_COOKIE_SECURE = (
    os.getenv("TASKILLER_ADMIN_CONSOLE_COOKIE_SECURE", str(TASKILLER_ENV != "local")).lower()
    == "true"
)
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([*CSRF_TRUSTED_ORIGINS, *ADMIN_CONSOLE_ORIGINS]))
if ADMIN_CONSOLE_ENABLED and TASKILLER_ENV == "production" and not ADMIN_CONSOLE_COOKIE_SECURE:
    raise ImproperlyConfigured("Production staff cookies must be Secure")
if ADMIN_CONSOLE_ENABLED:
    from cryptography.fernet import Fernet

    if not ADMIN_CONSOLE_ORIGINS or not ADMIN_CONSOLE_ENCRYPTION_KEYS:
        raise ImproperlyConfigured(
            "Enabled staff console requires exact origins and encryption keys"
        )
    for _console_origin in ADMIN_CONSOLE_ORIGINS:
        _parsed_origin = urlsplit(_console_origin)
        if (
            _parsed_origin.scheme
            not in ({"https"} if TASKILLER_ENV == "production" else {"https", "http"})
            or not _parsed_origin.netloc
            or _parsed_origin.path
            or _parsed_origin.query
            or _parsed_origin.fragment
            or _parsed_origin.username
            or "*" in _console_origin
        ):
            raise ImproperlyConfigured(
                "Staff console origins must be exact scheme://host[:port] values"
            )
    try:
        for _console_key in ADMIN_CONSOLE_ENCRYPTION_KEYS:
            Fernet(_console_key.encode())
    except (ValueError, TypeError) as _key_error:
        raise ImproperlyConfigured(
            "Staff console encryption keys must be valid Fernet keys"
        ) from _key_error
