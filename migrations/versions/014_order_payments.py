"""Record how an order is paid and log incoming SePay bank transfers.

Revision ID: 014_order_payments
Revises: 013_review_plant_id
Create Date: 2026-10-04

Every order gets a `payment_method` (`cod` or `bank_transfer`) and a
`payment_status` (`pending` or `paid`). Existing orders were all cash on
delivery, so the server default backfills them as `cod` / `pending`.

Bank-transfer orders carry a unique `payment_reference` the customer puts in
the transfer content. `payment_transactions` stores every SePay webhook once,
keyed by SePay's transaction id, so retried deliveries are never applied twice.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "014_order_payments"
down_revision: Union[str, None] = "013_review_plant_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

payment_method = postgresql.ENUM(
    "cod",
    "bank_transfer",
    name="payment_method",
    create_type=False,
)
payment_status = postgresql.ENUM(
    "pending",
    "paid",
    name="payment_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    payment_method.create(bind, checkfirst=True)
    payment_status.create(bind, checkfirst=True)

    op.add_column(
        "orders",
        sa.Column(
            "payment_method",
            payment_method,
            server_default="cod",
            nullable=False,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "payment_status",
            payment_status,
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("payment_reference", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_orders_payment_reference", "orders", ["payment_reference"]
    )
    op.create_index("ix_orders_payment_status", "orders", ["payment_status"])

    op.create_table(
        "payment_transactions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.String(length=32),
            server_default="sepay",
            nullable=False,
        ),
        sa.Column("provider_transaction_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=True),
        sa.Column("gateway", sa.String(length=100), nullable=True),
        sa.Column("account_number", sa.String(length=100), nullable=True),
        sa.Column("sub_account", sa.String(length=250), nullable=True),
        sa.Column("code", sa.String(length=250), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("transfer_type", sa.String(length=10), nullable=True),
        sa.Column("transfer_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("reference_code", sa.String(length=255), nullable=True),
        sa.Column("transaction_date", sa.String(length=32), nullable=True),
        sa.Column("match_status", sa.String(length=32), nullable=False),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
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
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_payment_transactions_order_id_orders",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_transaction_id",
            name="uq_payment_transactions_provider_transaction_id",
        ),
    )
    op.create_index(
        "ix_payment_transactions_order_id", "payment_transactions", ["order_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_payment_transactions_order_id", table_name="payment_transactions")
    op.drop_table("payment_transactions")
    op.drop_index("ix_orders_payment_status", table_name="orders")
    op.drop_constraint("uq_orders_payment_reference", "orders", type_="unique")
    op.drop_column("orders", "paid_at")
    op.drop_column("orders", "payment_reference")
    op.drop_column("orders", "payment_status")
    op.drop_column("orders", "payment_method")
    bind = op.get_bind()
    payment_status.drop(bind, checkfirst=True)
    payment_method.drop(bind, checkfirst=True)
