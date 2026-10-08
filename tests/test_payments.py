"""Bank transfer checkout and SePay webhook tests (run against TEST_DATABASE_URL)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.categories.models import Category
from app.features.orders.models import Order
from app.features.payments.models import PaymentTransaction
from app.features.plants.models import Plant

CHECKOUT_PATH = "/api/v1/storefront/orders"
WEBHOOK_PATH = "/api/v1/payments/sepay/webhook"
HUMAN_BOT_SIGNALS = {"website": "", "form_elapsed_ms": 5000}

API_KEY = "test-sepay-key"
ACCOUNT_NUMBER = "VQRQTEST00702"


@pytest_asyncio.fixture
async def sepay_client(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    """The API client with bank transfer configured."""
    monkeypatch.setenv("SEPAY_WEBHOOK_API_KEY", API_KEY)
    monkeypatch.setenv("SEPAY_ACCOUNT_NUMBER", ACCOUNT_NUMBER)
    monkeypatch.setenv("SEPAY_BANK_CODE", "MB")
    monkeypatch.setenv("SEPAY_BANK_NAME", "MB Bank")
    monkeypatch.setenv("SEPAY_ACCOUNT_HOLDER", "NGUYEN HOANG VIET")
    get_settings.cache_clear()
    yield client
    monkeypatch.undo()
    get_settings.cache_clear()


def _unique_phone() -> str:
    return f"09{uuid4().int % 100_000_000:08d}"


def _transaction_id() -> int:
    return uuid4().int % 10**12


async def _seed_plant(session: AsyncSession, category: Category) -> Plant:
    unique = uuid4().hex[:8]
    plant = Plant(
        category_id=category.id,
        name=f"Mit Thai {unique}",
        slug=f"mit-thai-{unique}",
        price=Decimal("240000.00"),
        price_vi=Decimal("240000.00"),
        stock=20,
        sku=f"MIT-{unique}",
        is_active=True,
    )
    session.add(plant)
    await session.commit()
    await session.refresh(plant)
    return plant


async def _checkout(client: AsyncClient, plant: Plant, **overrides: object):
    payload: dict = {
        "customer": {"phone": _unique_phone(), "name": "Nguyễn Văn A"},
        "shipping_address": "123 Nguyễn Huệ, Quận 1, TP.HCM",
        "items": [{"plant_id": str(plant.id), "quantity": 1}],
        **HUMAN_BOT_SIGNALS,
    }
    payload.update(overrides)
    return await client.post(CHECKOUT_PATH, json=payload)


async def _bank_transfer_order(client: AsyncClient, plant: Plant) -> dict:
    response = await _checkout(client, plant, payment_method="bank_transfer")
    assert response.status_code == 201, response.text
    return response.json()


def _webhook_body(**overrides: object) -> dict:
    body: dict = {
        "id": _transaction_id(),
        "gateway": "MBBank",
        "transactionDate": "2026-10-04 16:30:00",
        "accountNumber": "0123456789",
        "subAccount": ACCOUNT_NUMBER,
        "code": None,
        "content": "chuyen tien",
        "transferType": "in",
        "description": "BankAPINotify chuyen tien",
        "transferAmount": 290000,
        "accumulated": 1000000,
        "referenceCode": f"FT{uuid4().hex[:10].upper()}",
    }
    body.update(overrides)
    return body


async def _send_webhook(client: AsyncClient, body: dict, key: str | None = API_KEY):
    headers = {"Authorization": f"Apikey {key}"} if key is not None else {}
    return await client.post(WEBHOOK_PATH, json=body, headers=headers)


async def _order(session: AsyncSession, order_id: str) -> Order:
    session.expire_all()
    result = await session.execute(select(Order).where(Order.id == UUID(order_id)))
    return result.scalar_one()


async def _transactions(session: AsyncSession, transaction_id: int) -> list[PaymentTransaction]:
    session.expire_all()
    result = await session.execute(
        select(PaymentTransaction).where(
            PaymentTransaction.provider_transaction_id == transaction_id
        )
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_cod_checkout_is_unchanged_by_default(
    sepay_client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)

    response = await _checkout(sepay_client, plant)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["payment_method"] == "cod"
    assert body["payment_status"] == "pending"
    assert body["payment_reference"] is None
    assert body["payment"] is None


@pytest.mark.asyncio
async def test_bank_transfer_checkout_returns_payment_details(
    sepay_client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)

    body = await _bank_transfer_order(sepay_client, plant)

    reference = body["order_number"].replace("-", "")
    assert body["status"] == "pending"
    assert body["payment_method"] == "bank_transfer"
    assert body["payment_status"] == "pending"
    assert body["payment_reference"] == reference
    payment = body["payment"]
    assert payment["account_number"] == ACCOUNT_NUMBER
    assert payment["bank_code"] == "MB"
    assert payment["bank_name"] == "MB Bank"
    assert payment["account_holder"] == "NGUYEN HOANG VIET"
    assert Decimal(payment["amount"]) == Decimal("290000")
    assert payment["reference"] == reference
    assert payment["qr_url"].startswith("https://qr.sepay.vn/img?")
    assert f"acc={ACCOUNT_NUMBER}" in payment["qr_url"]
    assert "amount=290000" in payment["qr_url"]
    assert f"des={reference}" in payment["qr_url"]


@pytest.mark.asyncio
async def test_bank_transfer_checkout_unavailable_when_not_configured(
    client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEPAY_ACCOUNT_NUMBER", "")
    get_settings.cache_clear()
    plant = await _seed_plant(test_db_session, test_category)

    response = await _checkout(client, plant, payment_method="bank_transfer")

    assert response.status_code == 503
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    [pytest.param(None, id="missing"), pytest.param("wrong-key", id="wrong")],
)
async def test_webhook_rejects_bad_api_key(
    sepay_client: AsyncClient,
    test_db_session: AsyncSession,
    key: str | None,
) -> None:
    body = _webhook_body()

    response = await _send_webhook(sepay_client, body, key=key)

    assert response.status_code == 401
    assert await _transactions(test_db_session, body["id"]) == []


@pytest.mark.asyncio
async def test_webhook_marks_matching_order_paid(
    sepay_client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    order = await _bank_transfer_order(sepay_client, plant)
    body = _webhook_body(
        code=order["payment_reference"],
        content=f"{order['payment_reference']} thanh toan",
    )

    response = await _send_webhook(sepay_client, body)

    assert response.status_code == 200, response.text
    assert response.json() == {"success": True}
    stored = await _order(test_db_session, order["id"])
    assert stored.payment_status.value == "paid"
    assert stored.paid_at is not None
    assert stored.status.value == "pending"
    [transaction] = await _transactions(test_db_session, body["id"])
    assert transaction.match_status == "matched"
    assert transaction.order_id == UUID(order["id"])

    status_response = await sepay_client.get(f"{CHECKOUT_PATH}/{order['id']}/payment")
    assert status_response.status_code == 200
    assert status_response.json()["payment_status"] == "paid"


@pytest.mark.asyncio
async def test_webhook_matches_reference_in_content_without_code(
    sepay_client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    order = await _bank_transfer_order(sepay_client, plant)
    body = _webhook_body(
        code=None,
        content=f"MBVCB.123 {order['payment_reference'].lower()} chuyen khoan",
    )

    response = await _send_webhook(sepay_client, body)

    assert response.status_code == 200
    stored = await _order(test_db_session, order["id"])
    assert stored.payment_status.value == "paid"


@pytest.mark.asyncio
async def test_webhook_duplicate_delivery_is_a_no_op(
    sepay_client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    order = await _bank_transfer_order(sepay_client, plant)
    body = _webhook_body(code=order["payment_reference"])

    first = await _send_webhook(sepay_client, body)
    paid_at = (await _order(test_db_session, order["id"])).paid_at
    second = await _send_webhook(sepay_client, body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"success": True}
    assert len(await _transactions(test_db_session, body["id"])) == 1
    assert (await _order(test_db_session, order["id"])).paid_at == paid_at


@pytest.mark.asyncio
async def test_webhook_second_transfer_for_paid_order_is_recorded_only(
    sepay_client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    order = await _bank_transfer_order(sepay_client, plant)
    await _send_webhook(sepay_client, _webhook_body(code=order["payment_reference"]))
    again = _webhook_body(code=order["payment_reference"])

    response = await _send_webhook(sepay_client, again)

    assert response.status_code == 200
    [transaction] = await _transactions(test_db_session, again["id"])
    assert transaction.match_status == "already_paid"


@pytest.mark.asyncio
async def test_webhook_amount_mismatch_leaves_order_pending(
    sepay_client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    order = await _bank_transfer_order(sepay_client, plant)
    body = _webhook_body(code=order["payment_reference"], transferAmount=200000)

    response = await _send_webhook(sepay_client, body)

    assert response.status_code == 200
    assert response.json() == {"success": True}
    stored = await _order(test_db_session, order["id"])
    assert stored.payment_status.value == "pending"
    assert stored.paid_at is None
    [transaction] = await _transactions(test_db_session, body["id"])
    assert transaction.match_status == "amount_mismatch"
    assert transaction.order_id == UUID(order["id"])


@pytest.mark.asyncio
async def test_webhook_unmatched_code_is_recorded(
    sepay_client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    body = _webhook_body(code="GG999912310001", content="GG999912310001")

    response = await _send_webhook(sepay_client, body)

    assert response.status_code == 200
    [transaction] = await _transactions(test_db_session, body["id"])
    assert transaction.match_status == "unmatched"
    assert transaction.order_id is None


@pytest.mark.asyncio
async def test_webhook_outgoing_transfer_is_ignored(
    sepay_client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    order = await _bank_transfer_order(sepay_client, plant)
    body = _webhook_body(code=order["payment_reference"], transferType="out")

    response = await _send_webhook(sepay_client, body)

    assert response.status_code == 200
    stored = await _order(test_db_session, order["id"])
    assert stored.payment_status.value == "pending"
    [transaction] = await _transactions(test_db_session, body["id"])
    assert transaction.match_status == "ignored"


@pytest.mark.asyncio
async def test_webhook_never_matches_cod_orders(
    sepay_client: AsyncClient,
    test_category: Category,
    test_db_session: AsyncSession,
) -> None:
    plant = await _seed_plant(test_db_session, test_category)
    response = await _checkout(sepay_client, plant)
    order = response.json()
    reference = order["order_number"].replace("-", "")

    webhook = await _send_webhook(sepay_client, _webhook_body(code=reference))

    assert webhook.status_code == 200
    stored = await _order(test_db_session, order["id"])
    assert stored.payment_status.value == "pending"
    result = await test_db_session.execute(
        select(func.count()).select_from(PaymentTransaction).where(
            PaymentTransaction.order_id == UUID(order["id"])
        )
    )
    assert result.scalar_one() == 0
