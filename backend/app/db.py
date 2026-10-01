"""Подключение к БД (SQLAlchemy). PostgreSQL в эксплуатации, SQLite допустим для разработки и тестов."""
from collections.abc import Iterator
from pathlib import Path

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

JSONType = JSON().with_variant(JSONB(), "postgresql")


class UTCDateTime(TypeDecorator):
    """Дата и время всегда в UTC (SQLite не хранит часовой пояс, поэтому приводим явно)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        if ":memory:" not in url:
            path = url.split("///", 1)[-1]
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


def configure_engine(url: str | None = None) -> Engine:
    """Создаёт engine и фабрику сессий. Повторный вызов пересоздаёт их (используется в тестах)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = _make_engine(url or get_settings().database_url)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        configure_engine()
    assert _engine is not None
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        configure_engine()
    assert _session_factory is not None
    return _session_factory


BACKEND_DIR = Path(__file__).resolve().parent.parent


def run_migrations(url: str | None = None) -> None:
    """Применяет миграции Alembic до последней версии."""
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", (url or get_settings().database_url).replace("%", "%%"))
    command.upgrade(config, "head")


def init_db() -> None:
    from app import models  # noqa: F401  (регистрация таблиц)

    if get_settings().db_migrate:
        url = get_settings().database_url
        if url.startswith("sqlite") and ":memory:" not in url:
            Path(url.split("///", 1)[-1]).parent.mkdir(parents=True, exist_ok=True)
        run_migrations(url)
    else:
        Base.metadata.create_all(get_engine())


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
