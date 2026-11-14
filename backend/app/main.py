from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth, users
from app.core.config import get_settings
from app.db.seed import seed_first_admin
from app.db.session import SessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    async with SessionLocal() as session:
        await seed_first_admin(session, settings)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Uptime Monitor API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
    return app


app = create_app()
