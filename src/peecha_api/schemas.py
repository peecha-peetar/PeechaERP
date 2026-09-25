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
    # طبقِ درخواستِ صریحِ کاربر («برای ویزیت پخش سرد هم ویزیت و عکس و
    # سفارش باشه»): اختیاری -- برایِ هر دو نوعِ پخش.
    photo_base64: str | None = None


class VisitSkipRequest(BaseModel):
    skip_reason: str


class OrderLineRequest(BaseModel):
    item_id: int
    uom_id: int
    quantity: decimal.Decimal
    unit_price: decimal.Decimal
    # طبقِ باگِ واقعیِ کشف‌شده (R210): موبایل discount_amountِ برگشته از
    # GET /pricing/resolve را می‌گرفت ولی هیچ‌جا نمی‌فرستاد -- پس فاکتورِ
    # پخشِ گرم همیشه بدونِ تخفیف ثبت می‌شد. مالیات این‌جا نیست چون طبقِ
    # همان سیاستِ دسکتاپ سرور خودش (resolve_default_tax_percent) تعیین
    # می‌کند، نه کلاینت.
    discount_amount: decimal.Decimal = decimal.Decimal(0)


class ReceivedCheckRequest(BaseModel):
    """طبقِ درخواستِ صریح («فیلدهایِ چک دقیقاً همون فیلدهایِ دسکتاپ»):
    هم‌فرمت با چکِ دریافتیِ فرمِ دریافتِ خزانه‌داریِ دسکتاپ."""

    check_no: str
    due_date: datetime.date
    amount: decimal.Decimal
    check_serial: str | None = None
    bank_id: int | None = None
    check_bank_name: str | None = None
    iban: str | None = None
    bank_account_no: str | None = None
    party_name: str | None = None
    national_id: str | None = None
    phone: str | None = None


class OrderSettlementLineRequest(BaseModel):
    method_code: str
    amount: decimal.Decimal
    # طبقِ درخواستِ صریح («ثبتِ تسویه دقیقاً همون فیلدهایی که دسکتاپ داره»):
    # ستونِ «تفصیلی» (کدام صندوق/حسابِ بانکی) + یادداشت + چک‌ها (فقط CHECK).
    detail_account_id: int | None = None
    note: str | None = None
    checks: list[ReceivedCheckRequest] | None = None


class OrderCreateRequest(BaseModel):
    document_type_code: str  # "SALES_ORDER" (پخشِ سرد) یا "SALES_INVOICE" (پخشِ گرم)
    counterparty_detail_account_id: int
    warehouse_id: int
    channel_code: str
    currency_id: int
    lines: list[OrderLineRequest]
    post_immediately: bool = False  # فقط برایِ SALES_INVOICEِ پخشِ گرم
    # طبقِ درخواستِ صریح («در تنظیماتِ موبایل مرکزِ هزینه/پروژه تعیین
    # شود»): موبایل این‌ها را از پیش‌فرضِ کانال (GET /pricing/channels)
    # می‌خواند و بدونِ نمایشِ انتخاب‌گر به ویزیتور، همین‌جا می‌فرستد.
    cost_center_detail_account_id: int | None = None
    project_detail_account_id: int | None = None
    # طبقِ درخواستِ صریح («نوعِ تسویه در پخشِ گرم باید همانندِ انواعِ
    # تسویه در دسکتاپ باشد»): None یعنی موبایل هنوز آپدیت نشده (سازگاریِ
    # عقب‌رو -- رفتارِ قدیمیِ «۱۰۰٪ نقدی»)؛ فهرستِ خالی یعنی صراحتاً
    # «همه‌اش نسیه» (مانده‌یِ پوشش‌داده‌نشده خودکار محاسبه می‌شود).
    settlement_lines: list[OrderSettlementLineRequest] | None = None


class DeliveryConfirmationLineRequest(BaseModel):
    document_line_id: int
    delivered_quantity: decimal.Decimal
    shortage_reason: str | None = None


class PriceResolveResponse(BaseModel):
    unit_price: decimal.Decimal
    source: str  # CONTRACT | PRICE_LIST
    discount_amount: decimal.Decimal
    # طبقِ باگِ واقعیِ کشف‌شده (R210): فقط برایِ پیش‌نمایشِ مبلغِ نهاییِ
    # موبایل پیش از ثبت -- خودِ سرور هنگامِ ثبتِ سند دوباره و مستقلاً
    # (resolve_default_tax_percent) محاسبه می‌کند.
    tax_percent: decimal.Decimal


class PaymentMethodLineRequest(BaseModel):
    method: str  # "CASH" | "BANK" | "CHECK"
    amount: decimal.Decimal
    description: str = ""
    detail_account_id: int | None = None  # صندوق/حسابِ بانکیِ مشخص، اگر بیش از یکی نگاشته شده
    check_no: str | None = None
    check_bank_name: str | None = None
    check_due_date: datetime.date | None = None
    check_party_name: str | None = None


class PaymentCreateRequest(BaseModel):
    customer_detail_account_id: int
    document_date: datetime.date | None = None
    description: str = ""
    customer_visit_id: int | None = None
    method_lines: list[PaymentMethodLineRequest]


class CustomerCreateRequest(BaseModel):
    # طبقِ درخواستِ صریحِ کاربر («Customer Acquisition باید آفلاین هم کار
    # کند»): None یعنی سرور خودش، هنگامِ همگام‌سازیِ واقعی، کدِ بعدی را
    # پیشنهاد/اختصاص می‌دهد -- ویزیتورِ آفلاین نمی‌تواند کدِ بعدیِ شرکت
    # را از قبل بداند.
    code: str | None = None
    name: str
    customer_group_id: int | None = None
    default_price_list_id: int | None = None
    payment_term_days: int = 0
    credit_limit_amount: decimal.Decimal = decimal.Decimal(0)
    default_channel_code: str | None = None
    distribution_route_detail_account_id: int | None = None
    address: str | None = None
    phone: str | None = None
    mobile: str | None = None
    notes: str | None = None
    photo_base64: str | None = None
    gps_latitude: decimal.Decimal | None = None
    gps_longitude: decimal.Decimal | None = None


class CustomerRejectRequest(BaseModel):
    reason: str


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


class VehicleSettlementLineRequest(BaseModel):
    item_id: int
    uom_id: int
    returned_quantity: decimal.Decimal


class VehicleSettlementSubmitRequest(BaseModel):
    declared_cash_amount: decimal.Decimal
    lines: list[VehicleSettlementLineRequest]
