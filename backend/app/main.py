from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import auth, dashboard, monitors, notifications, users
from app.core.config import get_settings
from app.core.errors import public_errors
from app.db.seed import seed_first_admin
from app.db.session import SessionLocal
from app.notifications.service import DatabaseNotifier
from app.worker.checker import CheckRunner
from app.worker.scheduler import Scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    async with SessionLocal() as session:
        await seed_first_admin(session, settings)

    notifier = DatabaseNotifier(SessionLocal, settings)
    app.state.notifier = notifier
    runner = CheckRunner(
        SessionLocal,
        max_concurrent_checks=settings.max_concurrent_checks,
        user_agent=settings.probe_user_agent,
        ssl_inspect_timeout_seconds=settings.ssl_inspect_timeout_seconds,
        notifier=notifier,
        notification_timeout_seconds=settings.notification_timeout_seconds,
    )
    scheduler = Scheduler(runner, SessionLocal, settings)
    app.state.check_runner = runner
    app.state.scheduler = scheduler

    if settings.scheduler_enabled:
        scheduler.start()

    try:
        yield
    finally:
        await scheduler.stop()
        runner.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Uptime Monitor API", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": public_errors(exc)},
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
    app.include_router(monitors.router, prefix="/api/v1/monitors", tags=["monitors"])
    app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
    app.include_router(
        notifications.router,
        prefix="/api/v1/notifications",
        tags=["notifications"],
    )
    return app


app = create_app()
