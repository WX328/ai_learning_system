"""Store generated answer feedback separately from answer submission.

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("question_attempts", sa.Column("ai_feedback", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("question_attempts") as batch_op:
        batch_op.drop_column("ai_feedback")
