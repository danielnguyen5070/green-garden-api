"""Drop plant pot sizes and order item pot size snapshot.

Revision ID: 015_drop_pot_sizes
Revises: 014_order_payments
Create Date: 2026-10-18

Plants are sold at a single `price_vi`. Pot-size variants and the order-item
name snapshot are removed entirely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_drop_pot_sizes"
down_revision: Union[str, None] = "014_order_payments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_plant_pot_sizes_plant_id", table_name="plant_pot_sizes")
    op.drop_table("plant_pot_sizes")
    op.drop_column("order_items", "pot_size")


def downgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("pot_size", sa.String(length=100), nullable=True),
    )

    op.create_table(
        "plant_pot_sizes",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("plant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "price_adjustment",
            sa.Numeric(precision=12, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "price_adjustment_vi",
            sa.Numeric(precision=12, scale=2),
            nullable=True,
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default="true",
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
            "price_adjustment >= 0",
            name="ck_plant_pot_sizes_price_adjustment_non_negative",
        ),
        sa.CheckConstraint(
            "price_adjustment_vi >= 0",
            name="ck_plant_pot_sizes_price_adjustment_vi_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["plant_id"],
            ["plants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plant_pot_sizes_plant_id", "plant_pot_sizes", ["plant_id"])
