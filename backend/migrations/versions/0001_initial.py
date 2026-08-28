from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'favoritos' not in tables:
        op.create_table(
            'favoritos',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('usuario_id', sa.Integer(), nullable=False),
            sa.Column('tmdb_movie_id', sa.Integer(), nullable=False),
            sa.Column('titulo', sa.String(length=255), nullable=False),
            sa.Column('poster_path', sa.String(length=255), nullable=True),
            sa.Column('criado_em', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.UniqueConstraint('usuario_id', 'tmdb_movie_id', name='uniq_usuario_filme'),
            mysql_engine='InnoDB',
            mysql_charset='utf8mb4',
        )
    if 'comentarios' not in tables:
        op.create_table(
            'comentarios',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('usuario_id', sa.Integer(), nullable=False),
            sa.Column('tmdb_movie_id', sa.Integer(), nullable=False),
            sa.Column('texto', sa.Text(), nullable=False),
            sa.Column('criado_em', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP')),
            mysql_engine='InnoDB',
            mysql_charset='utf8mb4',
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'comentarios' in tables:
        op.drop_table('comentarios')
    if 'favoritos' in tables:
        op.drop_table('favoritos')
