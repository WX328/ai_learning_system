from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReviewAttempt(Base):
    """Reviews are separate from first answers and never award repeat XP."""
    __tablename__ = "review_attempts"
    __table_args__ = (UniqueConstraint("user_id", "request_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(36))
    user_answer: Mapped[str] = mapped_column(String(10))
    is_correct: Mapped[bool] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
