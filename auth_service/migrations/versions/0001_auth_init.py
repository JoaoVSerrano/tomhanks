"""Initial auth-service schema: usuarios e reset_tokens

Revision ID: 0001_auth_init
Revises:
Create Date: 2026-08-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0001_auth_init'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'usuarios' not in tables:
        op.create_table(
            'usuarios',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column('nome', sa.String(100), nullable=False),
            sa.Column('email', sa.String(150), nullable=False, unique=True),
            sa.Column('senha_hash', sa.String(255), nullable=False),
            sa.Column('role', sa.String(20), nullable=False, server_default='usuario'),
            sa.Column('criado_em', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        )
    else:
        columns = [c['name'] for c in inspector.get_columns('usuarios')]
        if 'role' not in columns:
            op.add_column('usuarios', sa.Column('role', sa.String(20), nullable=False, server_default='usuario'))

    if 'reset_tokens' not in tables:
        op.create_table(
            'reset_tokens',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column('token', sa.String(128), nullable=False, unique=True),
            sa.Column('usuario_id', sa.Integer(), sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
            sa.Column('criado_em', sa.TIMESTAMP(), nullable=False),
            sa.Column('expira_em', sa.TIMESTAMP(), nullable=False),
            sa.Column('usado', sa.Boolean(), nullable=False, default=False),
        )
        op.create_index('ix_reset_tokens_token', 'reset_tokens', ['token'], unique=True)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'reset_tokens' in tables:
        op.drop_index('ix_reset_tokens_token', table_name='reset_tokens')
        op.drop_table('reset_tokens')

    if 'usuarios' in tables:
        op.drop_table('usuarios')
