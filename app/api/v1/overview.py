"""Admin dashboard overview route (admin only, read-only).

One request returns every statistic the dashboard needs. All aggregation lives
in `app.services.overview_service`; this module only handles HTTP concerns.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_admin
from app.schemas.overview import OverviewResponse
from app.services.overview_service import LOW_STOCK_THRESHOLD, build_overview

router = APIRouter(
    prefix="/overview",
    tags=["overview"],
    dependencies=[Depends(get_current_admin)],
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"}},
)

_DESCRIPTION = f"""
Dashboard statistics for the admin panel, calculated live from the database.

**Auth:** an authenticated **active** admin (access cookie). There is no public
access and no caching — every call reads the current data.

**Revenue** counts orders with status `completed` only. `pending`,
`confirmed`, `processing`, `shipping` and `cancelled` orders are counted in
`summary.total_orders` and `orders_by_status`, but never earn money. Revenue is
`0.00` when nothing has been completed, never `null`.

**Sections**

- `summary` — catalogue, customer and order counters plus lifetime revenue.
- `sales.today` / `sales.this_month` — orders created in the period and the
  revenue of the completed ones, in UTC.
- `orders_by_status` — all six statuses (`pending`, `confirmed`, `processing`,
  `shipping`, `completed`, `cancelled`); unused statuses report `0`.
- `revenue_by_day` — one entry per day from the 1st of the current month up to
  today (UTC), chronological, including days with no sales.
- `top_plants` — the 5 best sellers across completed orders, named and priced
  from the `order_items` snapshots.
- `low_stock` — up to 5 **active** plants with `stock <= {LOW_STOCK_THRESHOLD}`,
  scarcest first.
- `recent_orders` — the 5 newest orders with their customer.

Money fields are `NUMERIC(12,2)` and serialize as JSON strings, like the rest
of the API.
"""


@router.get(
    "",
    response_model=OverviewResponse,
    summary="Dashboard overview",
    description=_DESCRIPTION,
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "description": "Statistics could not be calculated"
        }
    },
)
async def get_overview(db: AsyncSession = Depends(get_db)) -> OverviewResponse:
    try:
        stats = await build_overview(db)
    except SQLAlchemyError as exc:
        # Never leak the driver/SQL details to the dashboard.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to calculate the dashboard overview",
        ) from exc
    return OverviewResponse.model_validate(stats)
