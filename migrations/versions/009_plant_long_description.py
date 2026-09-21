"""Add plant long-form SEO description columns.

Revision ID: 009_plant_long_description
Revises: 008_notifications
Create Date: 2026-09-21

Nullable `TEXT` columns for English and Vietnamese long descriptions.
Existing rows keep their short `description` / `description_vi` unchanged.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_plant_long_description"
down_revision: Union[str, None] = "008_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plants",
        sa.Column("long_description", sa.Text(), nullable=True),
    )
    op.add_column(
        "plants",
        sa.Column("long_description_vi", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("plants", "long_description_vi")
    op.drop_column("plants", "long_description")
