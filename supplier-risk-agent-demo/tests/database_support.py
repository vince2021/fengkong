from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import backend.database as database


class IsolatedTestDatabase:
    """Temporarily route application sessions to a disposable SQLite database."""

    def __init__(self) -> None:
        self.directory = TemporaryDirectory()
        path = Path(self.directory.name) / "platform-test.db"
        self.engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
            pool_pre_ping=True,
        )
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.original_engine = database.engine
        self.original_session_factory = database.SessionLocal

    def start(self) -> None:
        database.Base.metadata.create_all(bind=self.engine)
        database.engine = self.engine
        database.SessionLocal = self.session_factory

    def stop(self) -> None:
        database.engine = self.original_engine
        database.SessionLocal = self.original_session_factory
        self.engine.dispose()
        self.directory.cleanup()
