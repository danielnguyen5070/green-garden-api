"""Attach reviews to plants.

Revision ID: 013_review_plant_id
Revises: 012_plant_slug_history
Create Date: 2026-10-04

Adds a nullable `plant_id` to `reviews`. NULL keeps the existing website-wide
shop reviews; a value makes the row a review of that plant. Reviews are
deleted together with their plant.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_review_plant_id"
down_revision: Union[str, None] = "012_plant_slug_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("plant_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_reviews_plant_id_plants",
        "reviews",
        "plants",
        ["plant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_reviews_plant_id_status_created_at",
        "reviews",
        ["plant_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reviews_plant_id_status_created_at", table_name="reviews")
    op.drop_constraint("fk_reviews_plant_id_plants", "reviews", type_="foreignkey")
    op.drop_column("reviews", "plant_id")
