"""Add Vietnamese name, description and price columns.

Revision ID: 003_vietnamese_fields
Revises: 002_categories_sort_order_index
Create Date: 2026-09-16

All new columns are nullable so existing rows keep their English values
untouched; no data is rewritten.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_vietnamese_fields"
down_revision: Union[str, None] = "002_categories_sort_order_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("name_vi", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "categories",
        sa.Column("description_vi", sa.Text(), nullable=True),
    )

    op.add_column(
        "plants",
        sa.Column("name_vi", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "plants",
        sa.Column("description_vi", sa.Text(), nullable=True),
    )
    op.add_column(
        "plants",
        sa.Column("price_vi", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    # NULL rows satisfy the check, so existing plants migrate without changes
    op.create_check_constraint(
        "ck_plants_price_vi_non_negative",
        "plants",
        "price_vi >= 0",
    )

    op.add_column(
        "plant_pot_sizes",
        sa.Column(
            "price_adjustment_vi",
            sa.Numeric(precision=12, scale=2),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_plant_pot_sizes_price_adjustment_vi_non_negative",
        "plant_pot_sizes",
        "price_adjustment_vi >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_plant_pot_sizes_price_adjustment_vi_non_negative",
        "plant_pot_sizes",
        type_="check",
    )
    op.drop_column("plant_pot_sizes", "price_adjustment_vi")

    op.drop_constraint(
        "ck_plants_price_vi_non_negative",
        "plants",
        type_="check",
    )
    op.drop_column("plants", "price_vi")
    op.drop_column("plants", "description_vi")
    op.drop_column("plants", "name_vi")

    op.drop_column("categories", "description_vi")
    op.drop_column("categories", "name_vi")
