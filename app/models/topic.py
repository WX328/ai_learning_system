from datetime import datetime,timezone

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class Topic(Base):
    __tablename__="topics"

    id:Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    material_id:Mapped[int] = mapped_column(
        ForeignKey("learning_materials.id"),
        nullable=False,
        index=True
    )

    name:Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )

    created_at:Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    description:Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
