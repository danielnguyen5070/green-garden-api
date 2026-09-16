"""Admin dashboard overview schemas (read-only statistics).

Money keeps the API-wide convention: `Decimal` / `NUMERIC(12,2)`, serialized as
a JSON string. Revenue always means `completed` orders only, and days are cut
in UTC like every other timestamp in the API.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.order import OrderStatus

__all__ = [
    "LowStockPlant",
    "OrdersByStatus",
    "OverviewResponse",
    "OverviewSummary",
    "RecentOrder",
    "RevenueByDay",
    "SalesOverview",
    "SalesPeriodStats",
    "TopPlant",
]


class OverviewSummary(BaseModel):
    """Catalogue, customer and order totals for the dashboard header cards."""

    model_config = ConfigDict(from_attributes=True)

    total_plants: int
    active_plants: int
    total_categories: int
    active_categories: int
    total_customers: int
    active_customers: int
    total_orders: int
    pending_orders: int
    total_revenue: Decimal


class SalesPeriodStats(BaseModel):
    """Orders created in a period and the revenue its completed orders earned."""

    model_config = ConfigDict(from_attributes=True)

    orders: int
    revenue: Decimal


class SalesOverview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    today: SalesPeriodStats
    this_month: SalesPeriodStats


class OrdersByStatus(BaseModel):
    """Every order status, including the ones with no orders at all."""

    model_config = ConfigDict(from_attributes=True)

    pending: int
    confirmed: int
    processing: int
    shipping: int
    completed: int
    cancelled: int


class RevenueByDay(BaseModel):
    """One calendar day of the current month, zero-sales days included."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    orders: int
    revenue: Decimal


class TopPlant(BaseModel):
    """Best seller, named and priced from the order item snapshots."""

    model_config = ConfigDict(from_attributes=True)

    plant_id: UUID
    plant_name: str
    quantity_sold: int
    revenue: Decimal


class LowStockPlant(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plant_id: UUID
    plant_name: str
    stock: int


class RecentOrder(BaseModel):
    """Latest order with its customer, flattened for the dashboard table."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_number: str
    customer_name: str | None
    customer_phone: str | None
    status: OrderStatus
    total_amount: Decimal
    created_at: datetime


class OverviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    summary: OverviewSummary
    sales: SalesOverview
    orders_by_status: OrdersByStatus
    revenue_by_day: list[RevenueByDay]
    top_plants: list[TopPlant]
    low_stock: list[LowStockPlant]
    recent_orders: list[RecentOrder]
