"""Create plant slug history table.

Revision ID: 012_plant_slug_history
Revises: 011_order_currency_shipping
Create Date: 2026-09-28

Stores the slugs a plant used before a rename so the storefront can resolve
old URLs and redirect them to the current slug.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_plant_slug_history"
down_revision: Union[str, None] = "011_order_currency_shipping"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plant_slug_history",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("plant_id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(
        "ix_plant_slug_history_plant_id", "plant_slug_history", ["plant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_plant_slug_history_plant_id", table_name="plant_slug_history")
    op.drop_table("plant_slug_history")
