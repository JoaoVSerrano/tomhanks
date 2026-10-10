from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote_plus

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

class Base(DeclarativeBase):
    pass

_REQUIRED = {
    'DB_HOST': 'Host do banco de dados MariaDB',
    'DB_USER': 'Usuário do banco de dados',
    'DB_PASSWORD': 'Senha do banco de dados',
    'DB_NAME': 'Nome do banco de dados',
}

_ALIASES = {
    'DB_HOST': 'PAYMENT_DB_HOST',
    'DB_USER': 'PAYMENT_DB_USER',
    'DB_PASSWORD': 'PAYMENT_DB_PASSWORD',
    'DB_NAME': 'PAYMENT_DB_NAME',
}

def _resolve(key: str) -> str | None:
    return os.getenv(_ALIASES.get(key, key)) or os.getenv(key)

def _check_required_env() -> None:
    missing = []
    for var, desc in _REQUIRED.items():
        alias = _ALIASES.get(var, var)
        if not _resolve(var):
            missing.append(f'  • {alias} ou {var} — {desc}')
    if missing:
        print(
            '[payment_service/database] ERRO: variáveis de ambiente obrigatórias não definidas:\n'
            + '\n'.join(missing),
            file=sys.stderr,
        )
        sys.exit(1)

def build_database_url() -> str:
    driver = _resolve('DB_DRIVER') or 'mysql+mysqlconnector'
    user = quote_plus(_resolve('DB_USER'))
    password = quote_plus(_resolve('DB_PASSWORD'))
    host = _resolve('DB_HOST')
    port = _resolve('DB_PORT') or os.getenv('DB_PORT') or '3306'
    name = _resolve('DB_NAME')

    return f'{driver}://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4'

_check_required_env()

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
    return Path(__file__).resolve().parent.parent / 'alembic-payment.ini'

def upgrade_database() -> None:
    config = Config(str(alembic_config_path()))
    config.set_main_option('sqlalchemy.url', build_database_url().replace('%', '%%'))
    try:
        command.upgrade(config, 'head')
    except Exception:
        pass
    Base.metadata.create_all(bind=engine)

@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
