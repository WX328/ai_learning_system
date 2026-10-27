from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class LearningChunk(Base):
    __tablename__="learning_chunks"

    id:Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    material_id:Mapped[int] = mapped_column(
        ForeignKey("learning_materials.id"),
        nullable=False,
        index=True
    )

    chunk_index:Mapped[int] = mapped_column(
        nullable=False
    )

    content:Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    embedding:Mapped[str |None] = mapped_column(
        Text,
        nullable=True
    )

    topic_id:Mapped[int | None] = mapped_column(
        ForeignKey("topics.id"),
        nullable=True,
        index=True
    )