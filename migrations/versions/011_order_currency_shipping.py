"""Record currency, subtotal and shipping fee on every order.

Revision ID: 011_order_currency_shipping
Revises: 010_plant_care_attributes
Create Date: 2026-09-28

VND is the only transaction currency, so `currency` is constrained to `'VND'`.
Existing orders are all treated as VND. Before this revision the storefront
folded the shipping fee into `total_amount`, so it is recovered as the part of
the total the item lines do not account for, and the new check keeps
`total_amount = subtotal_amount + shipping_fee` true from here on.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_order_currency_shipping"
down_revision: Union[str, None] = "010_plant_care_attributes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default="VND",
            nullable=False,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("subtotal_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "shipping_fee",
            sa.Numeric(12, 2),
            server_default="0",
            nullable=False,
        ),
    )

    # An order without lines keeps its whole total as the subtotal; a total
    # smaller than its lines (never expected) is clamped to zero shipping.
    op.execute(
        """
        UPDATE orders AS o
        SET shipping_fee = GREATEST(
                o.total_amount - COALESCE(lines.items_total, o.total_amount),
                0
            )
        FROM (
            SELECT orders.id AS order_id, SUM(oi.quantity * oi.unit_price) AS items_total
            FROM orders
            LEFT JOIN order_items AS oi ON oi.order_id = orders.id
            GROUP BY orders.id
        ) AS lines
        WHERE lines.order_id = o.id
        """
    )
    op.execute("UPDATE orders SET subtotal_amount = total_amount - shipping_fee")

    op.alter_column("orders", "subtotal_amount", nullable=False)
    op.create_check_constraint(
        "ck_orders_currency_vnd", "orders", "currency = 'VND'"
    )
    op.create_check_constraint(
        "ck_orders_subtotal_amount_non_negative", "orders", "subtotal_amount >= 0"
    )
    op.create_check_constraint(
        "ck_orders_shipping_fee_non_negative", "orders", "shipping_fee >= 0"
    )
    op.create_check_constraint(
        "ck_orders_total_is_subtotal_plus_shipping",
        "orders",
        "total_amount = subtotal_amount + shipping_fee",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_orders_total_is_subtotal_plus_shipping", "orders", type_="check"
    )
    op.drop_constraint("ck_orders_shipping_fee_non_negative", "orders", type_="check")
    op.drop_constraint(
        "ck_orders_subtotal_amount_non_negative", "orders", type_="check"
    )
    op.drop_constraint("ck_orders_currency_vnd", "orders", type_="check")
    op.drop_column("orders", "shipping_fee")
    op.drop_column("orders", "subtotal_amount")
    op.drop_column("orders", "currency")
