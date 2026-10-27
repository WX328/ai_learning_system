from datetime import datetime,timezone

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class QAHistory(Base):
    __tablename__="qa_histories"

    id:Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    user_id:Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    material_id:Mapped[int] = mapped_column(
        ForeignKey("learning_materials.id"),
        nullable=False,
        index=True
    )

    question:Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    answer:Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    created_at:Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
