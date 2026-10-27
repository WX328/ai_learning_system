"""Add durable learning coach sessions and command receipts."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("coach_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("learning_materials.id"), nullable=False),
        sa.Column("goal", sa.String(500), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_coach_sessions_user_id", "coach_sessions", ["user_id"])
    op.create_index("ix_coach_sessions_material_id", "coach_sessions", ["material_id"])
    op.create_table("coach_turns",
        sa.Column("session_id", sa.String(36), sa.ForeignKey("coach_sessions.id"), primary_key=True),
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
    )


def downgrade():
    op.drop_table("coach_turns")
    op.drop_table("coach_sessions")
