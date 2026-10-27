from datetime import datetime,timezone

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class UserAchievement(Base):
    __tablename__="user_achievements"

    id:Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    user_id:Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    achievement_id:Mapped[int] = mapped_column(
        ForeignKey("achievements.id"),
        nullable=False,
        index=True
    )

    earned_at:Mapped[datetime] = mapped_column(
        default=datetime.now(timezone.utc),
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "achievement_id",
            name="uq_user_achievement"
        ),
    )