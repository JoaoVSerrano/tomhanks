"""payment init

Revision ID: 0001_payment_init
Revises: 
Create Date: 2026-10-09 21:00:00.000000

"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision: str = '0001_payment_init'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    tables = inspector.get_table_names()

    if 'stripe_customers' not in tables:
        op.create_table(
            'stripe_customers',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('google_id', sa.String(length=255), nullable=False),
            sa.Column('stripe_customer_id', sa.String(length=255), nullable=False),
            sa.Column('criado_em', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('stripe_customer_id')
        )
        op.create_index(op.f('ix_stripe_customers_google_id'), 'stripe_customers', ['google_id'], unique=True)

    if 'processed_webhook_events' not in tables:
        op.create_table(
            'processed_webhook_events',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('stripe_event_id', sa.String(length=255), nullable=False),
            sa.Column('event_type', sa.String(length=100), nullable=False),
            sa.Column('processado_em', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_processed_webhook_events_stripe_event_id'), 'processed_webhook_events', ['stripe_event_id'], unique=True)

def downgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    tables = inspector.get_table_names()

    if 'processed_webhook_events' in tables:
        op.drop_index(op.f('ix_processed_webhook_events_stripe_event_id'), table_name='processed_webhook_events')
        op.drop_table('processed_webhook_events')

    if 'stripe_customers' in tables:
        op.drop_index(op.f('ix_stripe_customers_google_id'), table_name='stripe_customers')
        op.drop_table('stripe_customers')
