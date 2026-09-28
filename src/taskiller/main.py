from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from taskiller import __version__
from taskiller.api import health
from taskiller.api.router import api_router
from taskiller.auth.email import AuthEmailSender, DevelopmentLogEmailSender, SafeLogEmailSender
from taskiller.core.config import Settings, get_settings
from taskiller.core.logging import configure_logging
from taskiller.core.problems import install_problem_handlers
from taskiller.db.session import Database


def create_app(
    settings: Settings | None = None,
    *,
    email_sender: AuthEmailSender | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)
    database = Database(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await database.dispose()

    app = FastAPI(
        title="Taskiller API",
        description="Client-independent REST API for Taskiller.",
        version=__version__,
        openapi_version="3.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.database = database
    app.state.auth_email_sender = email_sender or (
        SafeLogEmailSender() if app_settings.is_production else DevelopmentLogEmailSender()
    )

    install_problem_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-Match"],
        expose_headers=["ETag", "Location", "Retry-After"],
    )

    app.include_router(health.router)
    app.include_router(api_router, prefix=app_settings.api_prefix)
    return app


app = create_app()
