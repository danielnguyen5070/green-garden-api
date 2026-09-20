"""Create website-wide customer reviews table.

Revision ID: 007_reviews
Revises: 006_plant_search_indexes
Create Date: 2026-09-20

Reviews belong to the shop as a whole (no plant_id). New submissions start as
`pending` and only `approved` rows appear on the public storefront.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007_reviews"
down_revision: Union[str, None] = "006_plant_search_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

review_status = postgresql.ENUM(
    "pending",
    "approved",
    "rejected",
    name="review_status",
    create_type=False,
)


def upgrade() -> None:
    review_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "reviews",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "status",
            review_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name="ck_reviews_rating_range",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reviews_status", "reviews", ["status"])
    op.create_index("ix_reviews_created_at", "reviews", ["created_at"])
    op.create_index(
        "ix_reviews_status_created_at",
        "reviews",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reviews_status_created_at", table_name="reviews")
    op.drop_index("ix_reviews_created_at", table_name="reviews")
    op.drop_index("ix_reviews_status", table_name="reviews")
    op.drop_table("reviews")
    review_status.drop(op.get_bind(), checkfirst=True)
