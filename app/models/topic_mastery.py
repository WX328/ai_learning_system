from datetime import datetime,timezone

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class TopicMastery(Base):
    """Write-through snapshot; public reads recompute from answer evidence.

    correct_rate stores historical first-answer accuracy, not the mastery index.
    """
    __tablename__="topic_masteries"

    id:Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    user_id:Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    topic_id:Mapped[int] = mapped_column(
        ForeignKey("topics.id"),
        nullable=False,
        index=True
    )

    mastery_score:Mapped[int] = mapped_column(
        default=0,
        nullable=False
    )

    correct_rate:Mapped[float] = mapped_column(
        default=0.0,
        nullable=False
    )

    attempt_count:Mapped[int] = mapped_column(
        default=0,
        nullable=False
    )

    updated_at:Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__=(
        UniqueConstraint(
            "user_id",
            "topic_id",
            name="uq_user_topic_mastery"
        ),
    )
