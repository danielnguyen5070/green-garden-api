"""Public storefront routes: the catalogue and the COD / bank-transfer checkout.

No authentication anywhere here. Only active plants are exposed, and checkout
reuses `app.services.order_service` — the same VND pricing, snapshots and stock
movements as the admin panel, with the shipping fee on top. The quote endpoint
runs that pricing without writing, so the cart and checkout show exactly what
the order will charge.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.text import normalize_slug
from app.models.order import ORDER_CURRENCY, Order, PaymentMethod
from app.features.plants.models import Plant, PlantImage, PlantImageType, PlantPotSize
from app.models.review import ReviewStatus
from app.features.categories.schemas import (
    PublicCategoryListItem,
    PublicCategoryListResponse,
)
from app.schemas.order import (
    ShippingPolicyResponse,
    StorefrontOrderCreate,
    StorefrontOrderResponse,
    StorefrontQuoteLine,
    StorefrontQuoteRequest,
    StorefrontQuoteResponse,
)
from app.schemas.payment import BankTransferInfo, StorefrontPaymentStatusResponse
from app.features.plants.schemas import (
    PlantImageResponse,
    PlantPotSizeResponse,
    PublicPlantDetail,
    PublicPlantImage,
    PublicPlantListItem,
    PublicPlantListResponse,
    PublicPlantSearchResponse,
    PublicPotSizeSummary,
)
from app.schemas.review import (
    PublicReviewListItem,
    PublicReviewListResponse,
    ReviewCreate,
    ReviewResponse,
)
from app.shared.bot_protection.http import (
    BOT_REJECTED_RESPONSES,
    verify_bot_signals_or_403,
)
from app.shared.bot_protection.service import (
    CheckoutRateLimitedError,
    check_checkout_phone_limit,
)
from app.features.categories.service import list_categories
from app.features.customers.service import CustomerInactiveError
from app.services.order_service import (
    FREE_SHIPPING_ABOVE,
    SHIPPING_FEE,
    InsufficientStockError,
    OrderItemInput,
    OrderNotFoundError,
    OrderSource,
    OrderTotalTooLargeError,
    PlantUnavailableError,
    PotSizeUnavailableError,
    amount_to_free_shipping,
    create_order,
    get_order,
    quote_order,
)
from app.services.payment_service import bank_transfer_info
from app.features.plants.dependencies import (
    PLANT_NOT_FOUND_RESPONSES,
    get_active_plant_or_404,
)
from app.features.plants.service import (
    primary_image_url,
    PlantNotFoundError,
    SearchLocale,
    SortField,
    SortOrder,
    get_plant_by_slug,
    list_plants,
    search_plants,
)
from app.services.review_service import (
    ReviewScope,
    create_review,
    get_review_summary,
    list_reviews,
)

router = APIRouter(prefix="/storefront", tags=["storefront"])


def _payment_info(order: Order) -> BankTransferInfo | None:
    details = bank_transfer_info(order)
    return BankTransferInfo(**details._asdict()) if details is not None else None


async def _public_review_page(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    plant_id: UUID | None = None,
    scope: ReviewScope | None = None,
) -> PublicReviewListResponse:
    items, total = await list_reviews(
        db,
        page=page,
        page_size=page_size,
        status=ReviewStatus.APPROVED,
        plant_id=plant_id,
        scope=scope,
    )
    summary = await get_review_summary(db, plant_id=plant_id, scope=scope)
    return PublicReviewListResponse(
        items=[PublicReviewListItem.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        average_rating=summary.average_rating,
        total_reviews=summary.total_reviews,
        rating_distribution=summary.rating_distribution,
    )


@router.get(
    "/reviews",
    response_model=PublicReviewListResponse,
    summary="List approved reviews (public)",
    description=(
        "Paginated website-wide customer reviews (plant reviews are excluded). "
        "Only `approved` reviews are returned, ordered by `created_at` "
        "descending, with the average rating and star distribution of all "
        "approved shop reviews."
    ),
)
async def get_public_reviews(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> PublicReviewListResponse:
    return await _public_review_page(
        db, page=page, page_size=page_size, scope="shop"
    )


@router.post(
    "/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a review (public)",
    description=(
        "Submit a website-wide customer review without authentication. The "
        "review is stored as `pending` and does not appear publicly until an "
        "admin approves it.\n\n"
        "Bot protection: the hidden `website` field must be empty and "
        "`form_elapsed_ms` must be at least 3000, otherwise `403`."
    ),
    responses=BOT_REJECTED_RESPONSES,
)
async def post_public_review(
    payload: ReviewCreate,
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    verify_bot_signals_or_403(payload)
    review = await create_review(
        db,
        name=payload.name,
        rating=payload.rating,
        content=payload.content,
    )
    return ReviewResponse.model_validate(review)


@router.get(
    "/plants/{slug}/reviews",
    response_model=PublicReviewListResponse,
    summary="List approved reviews of a plant (public)",
    description=(
        "Paginated approved reviews of one active plant, ordered by "
        "`created_at` descending, with the plant's average rating and star "
        "distribution. Old slugs resolve to the plant like the detail endpoint."
    ),
    responses=PLANT_NOT_FOUND_RESPONSES,
)
async def get_public_plant_reviews(
    slug: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> PublicReviewListResponse:
    plant = await get_active_plant_or_404(db, slug)
    return await _public_review_page(
        db, page=page, page_size=page_size, plant_id=plant.id
    )


@router.post(
    "/plants/{slug}/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a review of a plant (public)",
    description=(
        "Submit a review of one active plant without authentication. The "
        "review is stored as `pending` and does not appear publicly until an "
        "admin approves it.\n\n"
        "Bot protection: the hidden `website` field must be empty and "
        "`form_elapsed_ms` must be at least 3000, otherwise `403`."
    ),
    responses={**PLANT_NOT_FOUND_RESPONSES, **BOT_REJECTED_RESPONSES},
)
async def post_public_plant_review(
    slug: str,
    payload: ReviewCreate,
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    verify_bot_signals_or_403(payload)
    plant = await get_active_plant_or_404(db, slug)
    review = await create_review(
        db,
        name=payload.name,
        rating=payload.rating,
        content=payload.content,
        plant_id=plant.id,
    )
    return ReviewResponse.model_validate(review)


@router.get(
    "/shipping-policy",
    response_model=ShippingPolicyResponse,
    summary="Shipping fee and free-shipping threshold (public)",
    description=(
        "The flat delivery fee every order pays unless its subtotal is strictly "
        "above `free_shipping_above`. Amounts are in `currency` (always VND)."
    ),
)
async def get_shipping_policy() -> ShippingPolicyResponse:
    return ShippingPolicyResponse(
        currency=ORDER_CURRENCY,
        shipping_fee=SHIPPING_FEE,
        free_shipping_above=FREE_SHIPPING_ABOVE,
    )


@router.post(
    "/orders/quote",
    response_model=StorefrontQuoteResponse,
    summary="Price a cart (public)",
    description=(
        "Prices cart lines exactly as checkout would, without creating an "
        "order, locking rows or touching stock. Send only `plant_id`, "
        "`pot_size_id` and `quantity`; the backend returns the unit price, "
        "line total, localized names and image for every line, plus the "
        "subtotal, shipping fee and total in VND.\n\n"
        "A line that cannot be sold (unknown or inactive plant, no VND price, "
        "pot size no longer on sale) comes back with `available: false` and "
        "adds nothing to the totals, so the cart can flag it instead of "
        "failing. `max_quantity` is the plant's current stock; checkout "
        "rejects a quantity above it."
    ),
)
async def post_storefront_quote(
    payload: StorefrontQuoteRequest,
    db: AsyncSession = Depends(get_db),
) -> StorefrontQuoteResponse:
    priced = await quote_order(
        db,
        [
            OrderItemInput(
                plant_id=item.plant_id,
                quantity=item.quantity,
                pot_size_id=item.pot_size_id,
            )
            for item in payload.items
        ],
    )

    lines: list[StorefrontQuoteLine] = []
    for line in priced.lines:
        plant = line.plant
        # Unknown and inactive plants expose nothing beyond the requested ids.
        visible = plant is not None and plant.is_active
        lines.append(
            StorefrontQuoteLine(
                plant_id=line.item.plant_id,
                pot_size_id=(
                    line.pot_size.id if line.pot_size is not None else line.item.pot_size_id
                ),
                quantity=line.item.quantity,
                available=line.available,
                slug=plant.slug if visible else None,
                name=plant.name if visible else None,
                name_vi=plant.name_vi if visible else None,
                image_url=primary_image_url(plant) if visible else None,
                pot_size_name=line.pot_size.name if line.pot_size is not None else None,
                unit_price=line.unit_price,
                line_total=line.line_total,
                max_quantity=plant.stock if visible and line.available else 0,
            )
        )

    return StorefrontQuoteResponse(
        currency=priced.currency,
        lines=lines,
        subtotal_amount=priced.subtotal,
        shipping_fee=priced.shipping_fee,
        total_amount=priced.total,
        free_shipping_above=FREE_SHIPPING_ABOVE,
        amount_to_free_shipping=amount_to_free_shipping(priced.subtotal),
    )


@router.post(
    "/orders",
    response_model=StorefrontOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a public customer order",
    description=(
        "Public checkout. **No authentication**: shoppers have no account and "
        "never log in, and no card or bank credentials are collected.\n\n"
        "`payment_method` is `cod` (default, cash on delivery) or "
        "`bank_transfer`. A bank-transfer order gets a unique "
        "`payment_reference` and the response's `payment` block carries the "
        "bank, account/VA, amount, reference and a VietQR image URL. Its "
        "`payment_status` stays `pending` until the SePay webhook confirms a "
        "matching transfer. Bank transfer returns `503` when it is not "
        "configured on the server.\n\n"
        "The customer is identified by phone, normalized to the canonical "
        "Vietnamese form first (`+84901234567` and `84901234567` both become "
        "`0901234567`), so the same shopper is never duplicated. A known "
        "number reuses the existing customer (keeping the name already on "
        "file), an unknown one creates a customer.\n\n"
        "Everything is priced in VND: item names come from `plants.name_vi` "
        "(falling back to `name`), unit prices from `plants.price_vi` plus the "
        "pot size's `price_adjustment_vi`. Pot sizes are picked by "
        "`pot_size_id` (or the deprecated `pot_size` name); without either, "
        "the plant's first active pot size is used. The subtotal is the sum of "
        "`unit_price × quantity`, shipping is 50,000 VND unless the subtotal "
        "is above 500,000 VND, and `total_amount` is subtotal plus shipping. "
        "The response carries `currency`, `subtotal_amount`, `shipping_fee` "
        "and `total_amount` — prices or totals in the request body are "
        "ignored.\n\n"
        "Customer, order, item snapshots and the stock deduction commit in one "
        "transaction with the plant rows locked, so a rejected line leaves no "
        "partial order and no stock movement behind. New orders start as "
        "`pending`; the shop moves them on from the admin panel.\n\n"
        "Bot protection: the hidden `website` field must be empty and "
        "`form_elapsed_ms` must be at least 3000, otherwise `403`. Each "
        "normalized phone number may place at most 3 orders per hour; beyond "
        "that the response is `429` with a `Retry-After` header in seconds."
    ),
    responses={
        **BOT_REJECTED_RESPONSES,
        status.HTTP_400_BAD_REQUEST: {
            "description": "Order total too large, or the customer is deactivated"
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Too many recent orders for this phone number"
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Plant or selected pot size does not exist"
        },
        status.HTTP_409_CONFLICT: {
            "description": (
                "Insufficient stock, or the plant is not on sale in the "
                "Vietnamese storefront"
            )
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Bank transfer is not configured"
        },
    },
)
async def post_storefront_order(
    payload: StorefrontOrderCreate,
    db: AsyncSession = Depends(get_db),
) -> StorefrontOrderResponse:
    verify_bot_signals_or_403(payload)
    if (
        payload.payment_method is PaymentMethod.BANK_TRANSFER
        and not get_settings().bank_transfer_enabled()
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bank transfer is not available right now",
        )
    try:
        await check_checkout_phone_limit(db, payload.customer.phone)
    except CheckoutRateLimitedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many orders for this phone number. Please try again later.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    try:
        order = await create_order(
            db,
            customer_phone=payload.customer.phone,
            customer_name=payload.customer.name,
            customer_email=None,
            shipping_address=payload.shipping_address,
            note=payload.note,
            items=[
                OrderItemInput(
                    plant_id=item.plant_id,
                    quantity=item.quantity,
                    pot_size_id=item.pot_size_id,
                    pot_size=item.pot_size,
                )
                for item in payload.items
            ],
            source=OrderSource.STOREFRONT,
            payment_method=payload.payment_method,
        )
    except (PlantNotFoundError, PotSizeUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (InsufficientStockError, PlantUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (CustomerInactiveError, OrderTotalTooLargeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    response = StorefrontOrderResponse.model_validate(order)
    response.payment = _payment_info(order)
    return response


@router.get(
    "/orders/{order_id}/payment",
    response_model=StorefrontPaymentStatusResponse,
    summary="Payment status of a placed order (public)",
    description=(
        "Lets the thank-you page poll whether a bank transfer has been "
        "confirmed. Returns only the payment method, status and transfer "
        "details — never customer data. The order id is the unguessable UUID "
        "returned by checkout."
    ),
    responses={status.HTTP_404_NOT_FOUND: {"description": "Order not found"}},
)
async def get_storefront_order_payment(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> StorefrontPaymentStatusResponse:
    try:
        order = await get_order(db, order_id)
    except OrderNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return StorefrontPaymentStatusResponse(
        order_id=order.id,
        order_number=order.order_number,
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        paid_at=order.paid_at,
        payment=_payment_info(order),
    )
