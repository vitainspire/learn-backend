"""add week planning tables

Revision ID: a1b2c3d4e5f6
Revises: d501f26fb187
Create Date: 2026-04-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "d501f26fb187"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_uuid = UUID(as_uuid=False)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # week_plans
    # ------------------------------------------------------------------
    op.create_table(
        "week_plans",
        sa.Column("id", _uuid, primary_key=True),
        sa.Column(
            "teacher_id", _uuid,
            sa.ForeignKey("teachers.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "class_id", _uuid,
            sa.ForeignKey("classes.id", ondelete="SET NULL"),
            nullable=True, index=True,
        ),
        sa.Column("grade", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(100), nullable=False),
        sa.Column("week_start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("teacher_id", "week_start_date", name="uq_teacher_week"),
    )

    # ------------------------------------------------------------------
    # week_plan_days
    # ------------------------------------------------------------------
    op.create_table(
        "week_plan_days",
        sa.Column("id", _uuid, primary_key=True),
        sa.Column(
            "week_plan_id", _uuid,
            sa.ForeignKey("week_plans.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "topic_id", _uuid,
            sa.ForeignKey("topics.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "lesson_plan_id", _uuid,
            sa.ForeignKey("lesson_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("day_of_week", sa.Integer(), nullable=False,
                  comment="0=Monday .. 4=Friday"),
        sa.Column("concept_name", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("week_plan_id", "day_of_week", name="uq_week_day"),
    )

    # ------------------------------------------------------------------
    # post_class_feedback
    # ------------------------------------------------------------------
    op.create_table(
        "post_class_feedback",
        sa.Column("id", _uuid, primary_key=True),
        sa.Column(
            "day_id", _uuid,
            sa.ForeignKey("week_plan_days.id", ondelete="CASCADE"),
            nullable=False, unique=True, index=True,
        ),
        sa.Column("not_covered", sa.Text(), nullable=True),
        sa.Column("carry_forward", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("class_response", sa.String(20), nullable=False, server_default="confident"),
        sa.Column("needs_revisit", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("revisit_concept", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )

    # ------------------------------------------------------------------
    # weekly_summaries
    # ------------------------------------------------------------------
    op.create_table(
        "weekly_summaries",
        sa.Column("id", _uuid, primary_key=True),
        sa.Column(
            "week_plan_id", _uuid,
            sa.ForeignKey("week_plans.id", ondelete="CASCADE"),
            nullable=False, unique=True, index=True,
        ),
        sa.Column("summary_json", JSONB, nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("weekly_summaries")
    op.drop_table("post_class_feedback")
    op.drop_table("week_plan_days")
    op.drop_table("week_plans")
