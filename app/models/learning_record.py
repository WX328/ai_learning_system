from datetime import datetime,timezone

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class LearningRecord(Base):
    __tablename__="learning_records"

    id:Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    user_id:Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    content_type:Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    content_id:Mapped[int | None] = mapped_column(
        nullable=True
    )

    study_time:Mapped[int] = mapped_column(
        default=0,
        nullable=False
    )

    progress:Mapped[int] = mapped_column(
        default=0,
        nullable=False
    )

    created_at:Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
