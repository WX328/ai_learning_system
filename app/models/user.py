from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, CheckConstraint, text
from sqlalchemy.orm import Mapped,mapped_column

from app.database import Base

class User(Base):
    __tablename__="users"
    __table_args__ = (CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),)

    role: Mapped[str] = mapped_column(String(20), default="user", server_default="user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc), nullable=True)
    auth_version: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)

    id:Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )
    username:Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False
    )
    password_hash:Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    total_xp:Mapped[int] = mapped_column(
        default=0,
        nullable=False
    )

    level:Mapped[int] = mapped_column(
        default=1,
        nullable=False
    )

    correct_streak:Mapped[int] = mapped_column(
        default=0,
        nullable=False
    )
