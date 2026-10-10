from __future__ import annotations
from datetime import datetime
from sqlalchemy import Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class StripeCustomer(Base):
    """Vínculo entre google_id do usuário e customer_id da Stripe."""
    __tablename__ = 'stripe_customers'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    google_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    criado_em: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))

class ProcessedWebhookEvent(Base):
    """Registro de eventos de webhook processados — garante idempotência."""
    __tablename__ = 'processed_webhook_events'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stripe_event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    processado_em: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
