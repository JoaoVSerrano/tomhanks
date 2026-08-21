from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote_plus

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def build_database_url() -> str:
    driver = os.getenv('DB_DRIVER', 'mysql+mysqlconnector')
    user = quote_plus(os.getenv('DB_USER', 'root'))
    password = quote_plus(os.getenv('DB_PASSWORD', ''))
    host = os.getenv('DB_HOST', '127.0.0.1')
    port = os.getenv('DB_PORT', '3306')
    name = os.getenv('DB_NAME', 'tomhanks')

    auth = f'{user}:{password}@' if password else f'{user}@'
    return f'{driver}://{auth}{host}:{port}/{name}?charset=utf8mb4'


engine = create_engine(
    build_database_url(),
    pool_pre_ping=True,
    pool_recycle=int(os.getenv('DB_POOL_RECYCLE', '3600')),
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def alembic_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / 'alembic.ini'


def upgrade_database() -> None:
    config = Config(str(alembic_config_path()))
    config.set_main_option('sqlalchemy.url', build_database_url().replace('%', '%%'))
    command.upgrade(config, 'head')


@contextmanager
def session_scope() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
