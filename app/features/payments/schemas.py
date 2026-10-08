"""Bank transfer payment schemas: what the customer sees, and SePay's webhook."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.features.orders.models import PaymentMethod, PaymentStatus

__all__ = [
    "BankTransferInfo",
    "SePayWebhookPayload",
    "SePayWebhookResponse",
    "StorefrontPaymentStatusResponse",
]


class BankTransferInfo(BaseModel):
    """
    Where and how much to transfer. `reference` must be the transfer content:
    it is how the payment is matched to the order.
    """

    model_config = ConfigDict(from_attributes=True)

    bank_code: str
    bank_name: str
    account_number: str
    account_holder: str | None
    amount: Decimal
    reference: str
    qr_url: str


class StorefrontPaymentStatusResponse(BaseModel):
    """Payment state of one order for the thank-you page; no customer data."""

    order_id: UUID
    order_number: str
    payment_method: PaymentMethod
    payment_status: PaymentStatus
    paid_at: datetime | None
    payment: BankTransferInfo | None


class SePayWebhookPayload(BaseModel):
    """
    Transaction body SePay POSTs to the webhook URL.

    `id` is SePay's transaction id and the deduplication key. `code` is the
    payment code SePay extracted from `content`, or null when none was found.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: int
    gateway: str | None = None
    transaction_date: str | None = Field(default=None, alias="transactionDate")
    account_number: str | None = Field(default=None, alias="accountNumber")
    sub_account: str | None = Field(default=None, alias="subAccount")
    code: str | None = None
    content: str | None = None
    transfer_type: str | None = Field(default=None, alias="transferType")
    description: str | None = None
    transfer_amount: Decimal = Field(alias="transferAmount", ge=0)
    accumulated: Decimal | None = None
    reference_code: str | None = Field(default=None, alias="referenceCode")


class SePayWebhookResponse(BaseModel):
    """SePay treats a delivery as delivered only on `{"success": true}`."""

    success: bool = True
