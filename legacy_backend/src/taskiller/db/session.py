from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from taskiller.core.config import Settings


class Database:
    """Owns the lazy async SQLAlchemy engine and session factory."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = create_async_engine(
                self._settings.database_url,
                pool_pre_ping=True,
                pool_recycle=self._settings.database_pool_recycle_seconds,
                pool_size=self._settings.database_pool_size,
                max_overflow=self._settings.database_max_overflow,
                pool_timeout=self._settings.database_pool_timeout_seconds,
                pool_use_lifo=True,
            )
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        return self._session_factory

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def healthcheck(self) -> str | None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            ).scalar_one_or_none()
            return str(revision) if revision is not None else None

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
