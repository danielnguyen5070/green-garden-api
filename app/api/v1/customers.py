"""Customer management API routes (admin only)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_admin
from app.schemas.customer import (
    CustomerCreate,
    CustomerListResponse,
    CustomerResponse,
    CustomerStatusUpdate,
    CustomerUpdate,
)
from app.services.customer_service import (
    CustomerNotFoundError,
    CustomerPhoneConflictError,
    create_customer,
    get_customer,
    list_customers,
    set_customer_status,
    update_customer,
)

router = APIRouter(
    prefix="/customers",
    tags=["customers"],
    dependencies=[Depends(get_current_admin)],
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"}},
)

_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Customer not found"}}
_CONFLICT = {
    status.HTTP_409_CONFLICT: {"description": "Phone already used by another customer"}
}


def _map_customer_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, CustomerNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, CustomerPhoneConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise exc


@router.get(
    "",
    response_model=CustomerListResponse,
    summary="List customers",
    description=(
        "Paginated customer list for the admin dashboard, including deactivated "
        "customers. Ordered by `created_at` descending."
    ),
)
async def get_customers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(
        default=None,
        description="Match customer phone, name or email",
    ),
    is_active: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> CustomerListResponse:
    items, total = await list_customers(
        db,
        page=page,
        page_size=page_size,
        search=search,
        is_active=is_active,
    )
    return CustomerListResponse(
        items=[CustomerResponse.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Get customer",
    description="Return a single customer by id, active or inactive.",
    responses=_NOT_FOUND,
)
async def get_customer_detail(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    try:
        customer = await get_customer(db, customer_id)
    except CustomerNotFoundError as exc:
        raise _map_customer_errors(exc) from exc
    return CustomerResponse.model_validate(customer)


@router.post(
    "",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create customer",
    description=(
        "Create a customer. The phone number is the customer identity and must "
        "be unique; customers have no password and never log in."
    ),
    responses=_CONFLICT,
)
async def post_customer(
    payload: CustomerCreate,
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    try:
        customer = await create_customer(
            db,
            phone=payload.phone,
            name=payload.name,
            email=str(payload.email) if payload.email is not None else None,
        )
    except CustomerPhoneConflictError as exc:
        raise _map_customer_errors(exc) from exc
    return CustomerResponse.model_validate(customer)


@router.patch(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Update customer",
    description=(
        "Partial update of phone, name and email. Changing the phone re-checks "
        "uniqueness. Sending `\"email\": null` clears the email."
    ),
    responses={**_NOT_FOUND, **_CONFLICT},
)
async def patch_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    try:
        customer = await update_customer(
            db,
            customer_id,
            phone=payload.phone,
            name=payload.name,
            email=str(payload.email) if payload.email is not None else None,
            email_provided="email" in payload.model_fields_set,
        )
    except (CustomerNotFoundError, CustomerPhoneConflictError) as exc:
        raise _map_customer_errors(exc) from exc
    return CustomerResponse.model_validate(customer)


@router.patch(
    "/{customer_id}/status",
    response_model=CustomerResponse,
    summary="Activate or deactivate customer",
    description=(
        "Soft deactivation. Customer data is never deleted and existing orders "
        "stay intact, but an inactive customer cannot place new orders."
    ),
    responses=_NOT_FOUND,
)
async def patch_customer_status(
    customer_id: UUID,
    payload: CustomerStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    try:
        customer = await set_customer_status(
            db,
            customer_id,
            is_active=payload.is_active,
        )
    except CustomerNotFoundError as exc:
        raise _map_customer_errors(exc) from exc
    return CustomerResponse.model_validate(customer)
