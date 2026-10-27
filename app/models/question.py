from datetime import datetime,timezone

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class Question(Base):
    __tablename__="questions"

    id:Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    material_id:Mapped[int] = mapped_column(
        ForeignKey("learning_materials.id"),
        nullable=False,
        index=True
    )

    question_type:Mapped[str] = mapped_column(
        String(30),
        default="single_choice",
        nullable=False
    )

    question:Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    option_a:Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    option_b:Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    option_c:Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    option_d:Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    answer:Mapped[str] = mapped_column(
        String(10),
        nullable=False
    )

    explanation:Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    difficulty:Mapped[int] = mapped_column(
        default=1,
        nullable=False
    )

    is_adaptive: Mapped[bool] = mapped_column(
    default=False,
    nullable=False
    )

    created_at:Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    topic_id:Mapped[int | None] = mapped_column(
        ForeignKey("topics.id"),
        nullable=True,
        index=True
    )
