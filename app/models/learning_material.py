from datetime import datetime,timezone

from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class LearningMaterial(Base):
    __tablename__="learning_materials"

    id:Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    user_id:Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    title:Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )

    content:Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    material_type:Mapped[str] = mapped_column(
        String(50),
        default="text",
        nullable=False
    )

    created_at:Mapped[datetime] = mapped_column(
        default=datetime.now(timezone.utc),
        nullable=False
    )
