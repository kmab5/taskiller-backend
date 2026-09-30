"""Apply Alembic migrations under a PostgreSQL advisory lock."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from taskiller.core.config import get_settings

_MIGRATION_LOCK_KEY = 7_611_947_228_138_001


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _MIGRATION_LOCK_KEY})
            connection.commit()
            try:
                alembic_config = Config("alembic.ini")
                alembic_config.attributes["connection"] = connection
                command.upgrade(alembic_config, "head")
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": _MIGRATION_LOCK_KEY}
                )
                connection.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
