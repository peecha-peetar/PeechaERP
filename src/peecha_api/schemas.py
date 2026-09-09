"""مدل‌هایِ Pydanticِ درخواست/پاسخِ API -- طبقِ اصلِ معماری: این‌ها فقط
لایهٔ سریالایز/اعتبارسنجیِ ورودی‌اند، هیچ منطقی این‌جا محاسبه نمی‌شود."""

from __future__ import annotations

import datetime
import decimal

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str
    device_name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: int
    full_name: str
    company_id: int
    company_name: str


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class VisitStartRequest(BaseModel):
    customer_detail_account_id: int
    visit_plan_id: int | None = None
    check_in_latitude: decimal.Decimal | None = None
    check_in_longitude: decimal.Decimal | None = None


class VisitCompleteRequest(BaseModel):
    notes: str | None = None


class VisitSkipRequest(BaseModel):
    skip_reason: str


class OrderLineRequest(BaseModel):
    item_id: int
    uom_id: int
    quantity: decimal.Decimal
    unit_price: decimal.Decimal


class OrderCreateRequest(BaseModel):
    document_type_code: str  # "SALES_ORDER" (پخشِ سرد) یا "SALES_INVOICE" (پخشِ گرم)
    counterparty_detail_account_id: int
    warehouse_id: int
    channel_code: str
    currency_id: int
    lines: list[OrderLineRequest]
    post_immediately: bool = False  # فقط برایِ SALES_INVOICEِ پخشِ گرم


class DeliveryConfirmationLineRequest(BaseModel):
    document_line_id: int
    delivered_quantity: decimal.Decimal
    shortage_reason: str | None = None


class DeliveryConfirmationRequest(BaseModel):
    document_id: int
    customer_visit_id: int | None = None
    received_by_name: str | None = None
    signature_base64: str | None = None
    photo_base64: str | None = None
    gps_latitude: decimal.Decimal | None = None
    gps_longitude: decimal.Decimal | None = None
    notes: str | None = None
    lines: list[DeliveryConfirmationLineRequest]
