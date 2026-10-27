from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class Achievement(Base):
    __tablename__="achievements"

    id:Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    name:Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True
    )

    description:Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    xp_reward:Mapped[int] = mapped_column(
        default=0,
        nullable=False
    )

    condition_type:Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    condition_value:Mapped[int] = mapped_column(
        default=1,
        nullable=False
    )
