"""Durable coach state and idempotent command receipts."""
from datetime import datetime, timezone
from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class CoachSession(Base):
    __tablename__ = "coach_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("learning_materials.id"), index=True)
    goal: Mapped[str] = mapped_column(String(500))
    minutes: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), default="active")
    revision: Mapped[int] = mapped_column(default=0)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))


class CoachTurn(Base):
    __tablename__ = "coach_turns"
    session_id: Mapped[str] = mapped_column(ForeignKey("coach_sessions.id"), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
