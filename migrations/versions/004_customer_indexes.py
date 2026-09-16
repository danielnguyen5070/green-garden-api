"""Add customer name and status indexes for the admin customer list.

Revision ID: 004_customer_indexes
Revises: 003_vietnamese_fields
Create Date: 2026-09-16

`customers.phone` is already unique (indexed by the unique constraint) and the
order tables already index `order_number`, `customer_id`, `status`,
`created_at`, `order_id` and `plant_id`, so no other index is needed. Email is
only ever matched as a substring, which a btree index cannot serve.

"""

from typing import Sequence, Union

from alembic import op

revision: str = "004_customer_indexes"
down_revision: Union[str, None] = "003_vietnamese_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_customers_name", "customers", ["name"])
    op.create_index("ix_customers_is_active", "customers", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_customers_is_active", table_name="customers")
    op.drop_index("ix_customers_name", table_name="customers")
