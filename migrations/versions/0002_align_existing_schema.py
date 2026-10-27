"""Align the pre-Alembic learning.db with the mapped schema.

The initial revision creates the complete schema for new databases. This
revision only repairs objects missing from databases created by create_all
before the matching model fields and constraints were introduced.
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _has_topic_fk(inspector, table: str) -> bool:
    return any(fk["constrained_columns"] == ["topic_id"] and
               fk["referred_table"] == "topics"
               for fk in inspector.get_foreign_keys(table))


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    for table in ("learning_chunks", "questions"):
        if not _has_topic_fk(inspector, table):
            with op.batch_alter_table(table) as batch_op:
                batch_op.create_foreign_key(f"fk_{table}_topic_id_topics",
                                            "topics", ["topic_id"], ["id"])
        indexes = {index["name"] for index in sa.inspect(connection).get_indexes(table)}
        index_name = f"ix_{table}_topic_id"
        if index_name not in indexes:
            op.create_index(index_name, table, ["topic_id"])

    inspector = sa.inspect(connection)
    columns = {column["name"]: column for column in inspector.get_columns("topic_masteries")}
    unique = any(item["name"] == "uq_user_topic_mastery" and
                 set(item["column_names"]) == {"user_id", "topic_id"}
                 for item in inspector.get_unique_constraints("topic_masteries"))
    if columns["id"]["nullable"] or not unique:
        with op.batch_alter_table("topic_masteries") as batch_op:
            if columns["id"]["nullable"]:
                batch_op.alter_column("id", existing_type=sa.Integer(), nullable=False)
            if not unique:
                batch_op.create_unique_constraint("uq_user_topic_mastery", ["user_id", "topic_id"])
    indexes = {index["name"] for index in sa.inspect(connection).get_indexes("topic_masteries")}
    for column in ("id", "topic_id", "user_id"):
        name = f"ix_topic_masteries_{column}"
        if name not in indexes:
            op.create_index(name, "topic_masteries", [column])


def downgrade() -> None:
    # The upgrade may have been a no-op for a fresh database. Keep the
    # aligned schema intact when stepping back to revision 0001.
    pass
