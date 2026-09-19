"""Add plants.og_image_url for Open Graph / social previews.

Revision ID: 005_plant_og_image_url
Revises: 004_customer_indexes
Create Date: 2026-09-19

Nullable absolute public URL used by the storefront for generateMetadata().

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_plant_og_image_url"
down_revision: Union[str, None] = "004_customer_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plants",
        sa.Column("og_image_url", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("plants", "og_image_url")
