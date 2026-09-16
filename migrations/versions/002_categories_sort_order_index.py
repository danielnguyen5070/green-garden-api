"""Add index on categories.sort_order for the default listing order.

Revision ID: 002_categories_sort_order_index
Revises: 001_initial_schema
Create Date: 2026-09-16

"""

from typing import Sequence, Union

from alembic import op

revision: str = "002_categories_sort_order_index"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_categories_sort_order", "categories", ["sort_order"])


def downgrade() -> None:
    op.drop_index("ix_categories_sort_order", table_name="categories")
