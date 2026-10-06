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


# ---------------------------------------------------------------------------
# Variáveis obrigatórias — falha na inicialização se ausentes
# ---------------------------------------------------------------------------

_REQUIRED = {
    'DB_HOST': 'Host do banco de dados MariaDB',
    'DB_USER': 'Usuário do banco de dados',
    'DB_PASSWORD': 'Senha do banco de dados',
    'DB_NAME': 'Nome do banco de dados',
}


def _check_required_env() -> None:
    """Aborta a inicialização se variáveis obrigatórias estiverem ausentes.

    Lista TODAS as variáveis faltantes antes de encerrar, sem imprimir valores.
    """
    missing = [f'  • {var} — {desc}' for var, desc in _REQUIRED.items() if not os.getenv(var)]
    if missing:
        print(
            '[database] ERRO: variáveis de ambiente obrigatórias não definidas:\n'
            + '\n'.join(missing)
            + '\n\nDefina-as nas variáveis de ambiente do container (seção *Environment* da stack no Portainer).',
            file=sys.stderr,
        )
        sys.exit(1)


def build_database_url() -> str:
    driver = os.getenv('DB_DRIVER') or 'mysql+mysqlconnector'
    user = quote_plus(os.environ['DB_USER'])
    password = quote_plus(os.environ['DB_PASSWORD'])
    host = os.environ['DB_HOST']
    port = os.getenv('DB_PORT') or '3306'
    name = os.environ['DB_NAME']

    return f'{driver}://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4'


# Validação executada no momento da importação do módulo
_check_required_env()

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
