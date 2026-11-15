"""Database engine and session management (SQLite locally, PostgreSQL-compatible)."""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def utcnow() -> datetime:
    """Naive UTC timestamp. All persisted datetimes are naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def init_engine(url: str) -> Engine:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database engine is not initialised")
    return _engine


def new_session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("Database engine is not initialised")
    return _SessionLocal()


def get_db() -> Iterator[Session]:
    db = new_session()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    from app import models  # noqa: F401  (register tables)

    Base.metadata.create_all(get_engine())
