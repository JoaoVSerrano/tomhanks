"""Adiciona google_id e torna senha_hash nullable.

Revision ID: 0002_google_oauth
Revises: 0001_auth_init
Create Date: 2026-10-09 21:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = '0002_google_oauth'
down_revision = '0001_auth_init'
branch_labels = None
depends_on = None

def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    columns = [col['name'] for col in inspector.get_columns('usuarios')]

    op.alter_column(
        'usuarios',
        'senha_hash',
        existing_type=sa.String(length=255),
        nullable=True
    )

    if 'google_id' not in columns:
        op.add_column('usuarios', sa.Column('google_id', sa.String(length=255), nullable=True))
        op.create_index(op.f('ix_usuarios_google_id'), 'usuarios', ['google_id'], unique=True)

def downgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    columns = [col['name'] for col in inspector.get_columns('usuarios')]

    if 'google_id' in columns:
        op.drop_index(op.f('ix_usuarios_google_id'), table_name='usuarios')
        op.drop_column('usuarios', 'google_id')

    op.alter_column(
        'usuarios',
        'senha_hash',
        existing_type=sa.String(length=255),
        nullable=False
    )
