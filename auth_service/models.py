from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = 'usuarios'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default='usuario')
    criado_em: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))

    reset_tokens = relationship('ResetToken', back_populates='user', cascade='all, delete-orphan')


class ResetToken(Base):
    """Tabela de tokens de recuperação de senha com expiração real."""
    __tablename__ = 'reset_tokens'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    expira_em: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    usado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user = relationship('User', back_populates='reset_tokens')
