from datetime import datetime,timezone

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class QuestionAttempt(Base):
    __tablename__="question_attempts"

    id:Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    user_id:Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    question_id:Mapped[int] = mapped_column(
        ForeignKey("questions.id"),
        nullable=False,
        index=True
    )

    user_answer:Mapped[str] = mapped_column(
        String(10),
        nullable=False
    )

    is_correct:Mapped[bool] = mapped_column(
        nullable=False
    )

    earned_xp:Mapped[int] = mapped_column(
        default=0,
        nullable=False
    )

    ai_feedback:Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at:Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
