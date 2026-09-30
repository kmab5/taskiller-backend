import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from taskiller import __version__
from taskiller.api import health
from taskiller.api.router import api_router
from taskiller.auth.email import (
    AuthEmailSender,
    DevelopmentLogEmailSender,
    SafeLogEmailSender,
    SMTPEmailSender,
)
from taskiller.core.config import EmailDeliveryMode, Settings, get_settings
from taskiller.core.logging import configure_logging
from taskiller.core.openapi import install_openapi_contract
from taskiller.core.problems import install_problem_handlers
from taskiller.core.runtime import install_runtime_middleware
from taskiller.db.session import Database
from taskiller.operations.worker import run_worker_loop

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    email_sender: AuthEmailSender | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)
    database = Database(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        worker_stop: asyncio.Event | None = None
        worker_task: asyncio.Task[None] | None = None
        if app_settings.embedded_worker_enabled:
            worker_stop = asyncio.Event()
            worker_task = asyncio.create_task(
                run_worker_loop(database, app_settings, stop_event=worker_stop),
                name="taskiller-embedded-outbox-worker",
            )
            logger.info("embedded_outbox_worker_started")
        try:
            yield
        finally:
            if worker_stop is not None and worker_task is not None:
                worker_stop.set()
                try:
                    await asyncio.wait_for(worker_task, timeout=10)
                except TimeoutError:
                    worker_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await worker_task
                    logger.warning("embedded_outbox_worker_cancelled_on_shutdown")
                except Exception:
                    logger.exception("embedded_outbox_worker_failed")
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
    if email_sender is not None:
        app.state.auth_email_sender = email_sender
    elif app_settings.email_delivery_mode is EmailDeliveryMode.SMTP:
        app.state.auth_email_sender = SMTPEmailSender(app_settings)
    elif app_settings.email_delivery_mode is EmailDeliveryMode.SAFE_LOG:
        app.state.auth_email_sender = SafeLogEmailSender()
    else:
        app.state.auth_email_sender = DevelopmentLogEmailSender()

    install_problem_handlers(app)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=app_settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "X-Request-ID",
        ],
        expose_headers=["ETag", "Location", "Retry-After", "X-Request-ID"],
    )
    install_runtime_middleware(app, app_settings)

    app.include_router(health.router)
    app.include_router(api_router, prefix=app_settings.api_prefix)
    install_openapi_contract(app, api_prefix=app_settings.api_prefix)
    return app


app = create_app()
