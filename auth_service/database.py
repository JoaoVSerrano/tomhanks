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
    driver = os.getenv('AUTH_DB_DRIVER') or os.getenv('DB_DRIVER') or 'mysql+mysqlconnector'
    user = quote_plus(os.getenv('AUTH_DB_USER') or os.getenv('DB_USER') or 'IAC_2026_02_joao_serrano')
    password = quote_plus(os.getenv('AUTH_DB_PASSWORD') or os.getenv('DB_PASSWORD') or 'Jv03p19m11!')
    host = os.getenv('AUTH_DB_HOST') or os.getenv('DB_HOST') or '35.226.64.52'
    port = os.getenv('AUTH_DB_PORT') or os.getenv('DB_PORT') or '3306'
    name = os.getenv('AUTH_DB_NAME') or os.getenv('DB_NAME') or 'IAC_2026_02_joao_serrano'

    auth = f'{user}:{password}@' if password else f'{user}@'
    return f'{driver}://{auth}{host}:{port}/{name}?charset=utf8mb4'


engine = create_engine(
    build_database_url(),
    pool_pre_ping=True,
    pool_recycle=int(os.getenv('DB_POOL_RECYCLE', '3600')),
    pool_size=int(os.getenv('DB_POOL_SIZE', '5')),
    max_overflow=int(os.getenv('DB_MAX_OVERFLOW', '2')),
    pool_timeout=int(os.getenv('DB_POOL_TIMEOUT', '10')),
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def alembic_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / 'alembic-auth.ini'


from sqlalchemy import create_engine, text

def upgrade_database() -> None:
    config = Config(str(alembic_config_path()))
    config.set_main_option('sqlalchemy.url', build_database_url().replace('%', '%%'))
    try:
        command.upgrade(config, 'head')
    except Exception:
        pass
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN bio TEXT NULL"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN avatar_key VARCHAR(255) NULL"))
        except Exception:
            pass


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
