"""Order management API routes (admin only).

Orders are historical business records: there is no `DELETE`. Pricing, stock and
status rules live in `app.services.order_service`.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.order import OrderStatus
from app.schemas.order import (
    OrderCreate,
    OrderListResponse,
    OrderResponse,
    OrderStatusUpdate,
)
from app.services.customer_service import CustomerInactiveError
from app.services.order_service import (
    InsufficientStockError,
    InvalidStatusTransitionError,
    OrderItemInput,
    OrderNotFoundError,
    OrderTotalTooLargeError,
    PlantUnavailableError,
    create_order,
    get_order,
    list_orders,
    update_order_status,
)
from app.services.plant_service import PlantNotFoundError

router = APIRouter(
    prefix="/orders",
    tags=["orders"],
    dependencies=[Depends(get_current_admin)],
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"}},
)

_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Order or plant not found"}}
_BAD_REQUEST = {
    status.HTTP_400_BAD_REQUEST: {
        "description": (
            "Insufficient stock, unavailable plant or pot size, inactive "
            "customer, or invalid status transition"
        )
    }
}


def _map_order_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, (OrderNotFoundError, PlantNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(
        exc,
        (
            InsufficientStockError,
            PlantUnavailableError,
            CustomerInactiveError,
            InvalidStatusTransitionError,
            OrderTotalTooLargeError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.get(
    "",
    response_model=OrderListResponse,
    summary="List orders",
    description=(
        "Paginated order list with customer and item snapshots eager-loaded. "
        "Ordered by `created_at` descending."
    ),
)
async def get_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(
        default=None,
        description="Match order number, customer phone or customer name",
    ),
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    customer_id: UUID | None = Query(default=None),
    date_from: date | None = Query(
        default=None,
        description="Created on or after this date (UTC, `YYYY-MM-DD`)",
    ),
    date_to: date | None = Query(
        default=None,
        description="Created on or before this date (UTC, `YYYY-MM-DD`)",
    ),
    db: AsyncSession = Depends(get_db),
) -> OrderListResponse:
    items, total = await list_orders(
        db,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        customer_id=customer_id,
        date_from=date_from,
        date_to=date_to,
    )
    return OrderListResponse(
        items=[OrderResponse.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Get order",
    description="Full order detail: customer, item snapshots, total and address.",
    responses=_NOT_FOUND,
)
async def get_order_detail(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    try:
        order = await get_order(db, order_id)
    except OrderNotFoundError as exc:
        raise _map_order_errors(exc) from exc
    return OrderResponse.model_validate(order)


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create order",
    description=(
        "Create an order for the given phone number, reusing the existing "
        "customer or creating a new one. Unit prices and the total are "
        "calculated from the current plant price plus the selected pot size "
        "adjustment — money sent by the client is ignored. Stock is verified "
        "and deducted in the same transaction; the order starts as `pending`."
    ),
    responses={**_NOT_FOUND, **_BAD_REQUEST},
)
async def post_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    try:
        order = await create_order(
            db,
            customer_phone=payload.customer.phone,
            customer_name=payload.customer.name,
            customer_email=(
                str(payload.customer.email)
                if payload.customer.email is not None
                else None
            ),
            shipping_address=payload.shipping_address,
            note=payload.note,
            items=[
                OrderItemInput(
                    plant_id=item.plant_id,
                    quantity=item.quantity,
                    pot_size=item.pot_size,
                )
                for item in payload.items
            ],
        )
    except (
        PlantNotFoundError,
        PlantUnavailableError,
        InsufficientStockError,
        CustomerInactiveError,
        OrderTotalTooLargeError,
    ) as exc:
        raise _map_order_errors(exc) from exc
    return OrderResponse.model_validate(order)


@router.patch(
    "/{order_id}/status",
    response_model=OrderResponse,
    summary="Update order status",
    description=(
        "Move the order forward through `pending`, `confirmed`, `processing`, "
        "`shipping`, `completed`, or cancel it from any non-terminal status. "
        "Cancelling returns the ordered quantities to stock exactly once; "
        "`completed` and `cancelled` are final. Re-sending the current status "
        "changes nothing."
    ),
    responses={**_NOT_FOUND, **_BAD_REQUEST},
)
async def patch_order_status(
    order_id: UUID,
    payload: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    try:
        order = await update_order_status(db, order_id, status=payload.status)
    except (OrderNotFoundError, InvalidStatusTransitionError) as exc:
        raise _map_order_errors(exc) from exc
    return OrderResponse.model_validate(order)
