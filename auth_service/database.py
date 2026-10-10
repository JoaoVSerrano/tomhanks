from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote_plus

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Variáveis obrigatórias — falha na inicialização se ausentes
# ---------------------------------------------------------------------------

_REQUIRED = {
    'DB_HOST': 'Host do banco de dados MariaDB',
    'DB_USER': 'Usuário do banco de dados',
    'DB_PASSWORD': 'Senha do banco de dados',
    'DB_NAME': 'Nome do banco de dados',
}

# Aliases AUTH_DB_* têm prioridade; se não definidos, cai em DB_*
_ALIASES = {
    'DB_HOST': 'AUTH_DB_HOST',
    'DB_USER': 'AUTH_DB_USER',
    'DB_PASSWORD': 'AUTH_DB_PASSWORD',
    'DB_NAME': 'AUTH_DB_NAME',
}


def _resolve(key: str) -> str | None:
    """Retorna o valor de AUTH_DB_KEY ou DB_KEY, nessa ordem."""
    return os.getenv(_ALIASES.get(key, key)) or os.getenv(key)


def _check_required_env() -> None:
    """Aborta a inicialização se variáveis obrigatórias estiverem ausentes.

    Lista TODAS as variáveis faltantes antes de encerrar, sem imprimir valores.
    """
    missing = []
    for var, desc in _REQUIRED.items():
        alias = _ALIASES.get(var, var)
        if not _resolve(var):
            missing.append(f'  • {alias} ou {var} — {desc}')
    if missing:
        print(
            '[auth_service/database] ERRO: variáveis de ambiente obrigatórias não definidas:\n'
            + '\n'.join(missing)
            + '\n\nDefina-as nas variáveis de ambiente do container (seção *Environment* da stack no Portainer).',
            file=sys.stderr,
        )
        sys.exit(1)


def build_database_url() -> str:
    driver = _resolve('DB_DRIVER') or 'mysql+mysqlconnector'
    user = quote_plus(_resolve('DB_USER'))         # type: ignore[arg-type]
    password = quote_plus(_resolve('DB_PASSWORD'))  # type: ignore[arg-type]
    host = _resolve('DB_HOST')
    port = _resolve('DB_PORT') or os.getenv('DB_PORT') or '3306'
    name = _resolve('DB_NAME')

    return f'{driver}://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4'


# Validação executada no momento da importação do módulo
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
    return Path(__file__).resolve().parent.parent / 'alembic-auth.ini'


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
            conn.execute(text('ALTER TABLE usuarios ADD COLUMN bio TEXT NULL'))
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE usuarios ADD COLUMN avatar_key VARCHAR(255) NULL'))
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE usuarios MODIFY COLUMN senha_hash VARCHAR(255) NULL'))
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE usuarios ADD COLUMN google_id VARCHAR(255) NULL'))
        except Exception:
            pass
        try:
            conn.execute(text('CREATE UNIQUE INDEX ix_usuarios_google_id ON usuarios (google_id)'))
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
