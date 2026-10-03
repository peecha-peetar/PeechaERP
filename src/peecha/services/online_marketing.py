"""مدیریتِ بازاریابیِ فروشگاهِ اینترنتی -- طبقِ بازخوردِ صریحِ کاربر
(«امکاناتِ حیاتیِ PeechaSync -- مدیریتِ بازاریابی»): ترکیبِ فروشِ
واقعی (compute_sales_report_by_item) و موجودیِ لحظه‌ای برایِ کالاهایِ
منتشرشده در فروشگاه -- پیشنهادِ اقدام (تخفیف/تامینِ مجدد/تولیدِ محتوا)
برایِ هرکدام، به‌علاوهٔ یادآوریِ تقویمِ مناسبتیِ فروشگاهی."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

import jdatetime
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import MarketplaceConnection, MarketplaceItemMapping
from peecha.services import commercial_documents as documents_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_engine as engine_service

_ZERO = decimal.Decimal("0")
_HIGH_STOCK_THRESHOLD = 20
_LOW_STOCK_THRESHOLD = 5


@dataclass
class ProductMarketingRow:
    item_id: int
    item_code: str
    item_name: str
    stock_available: decimal.Decimal
    quantity_sold: decimal.Decimal
    net_revenue: decimal.Decimal
    suggested_action: str


def _online_item_ids(company_id: int) -> set[int]:
    with new_session() as session:
        connection_ids = session.scalars(
            select(MarketplaceConnection.connection_id).where(MarketplaceConnection.company_id == company_id)
        ).all()
        if not connection_ids:
            return set()
        return set(
            session.scalars(
                select(MarketplaceItemMapping.item_id).where(MarketplaceItemMapping.connection_id.in_(connection_ids))
            )
        )


def _suggest_action(stock: decimal.Decimal, quantity_sold: decimal.Decimal) -> str:
    if quantity_sold == 0 and stock > 0:
        return "بدونِ فروش -- پیشنهاد: تخفیفِ معرفی (١۵-٢۵٪) یا بازبینیِ تصاویر/توضیحات/سئو"
    if stock >= _HIGH_STOCK_THRESHOLD and quantity_sold <= 2:
        return "موجودیِ بالا، فروشِ کم -- پیشنهاد: تخفیف یا کمپینِ ویژه برایِ این کالا"
    if 0 < stock <= _LOW_STOCK_THRESHOLD and quantity_sold > 0:
        return "موجودی رو به اتمام -- پیشنهاد: سفارشِ تامینِ مجدد قبل از تمام‌شدن"
    if quantity_sold >= 10:
        return "پرفروش -- پیشنهاد: تولیدِ محتوا/پستِ شبکهٔ اجتماعی برایِ این کالا"
    return ""


def compute_marketing_overview(
    company_id: int, date_from: datetime.date, date_to: datetime.date,
) -> list[ProductMarketingRow]:
    online_item_ids = _online_item_ids(company_id)
    if not online_item_ids:
        return []

    sales_rows = {r.item_id: r for r in documents_service.compute_sales_report_by_item(company_id, date_from, date_to)}
    items_by_id = {item.item_id: item for item in catalog_service.list_items(company_id) if item.item_id in online_item_ids}
    stock_by_item: dict[int, decimal.Decimal] = {}
    for item_id in online_item_ids:
        balances = engine_service.list_balances(company_id=company_id, item_id=item_id)
        stock_by_item[item_id] = sum((b.quantity_available for b in balances), _ZERO)

    rows = []
    for item_id, item in items_by_id.items():
        sale = sales_rows.get(item_id)
        quantity_sold = sale.quantity_sold if sale else _ZERO
        net_revenue = sale.net_revenue if sale else _ZERO
        stock = stock_by_item.get(item_id, _ZERO)
        rows.append(ProductMarketingRow(
            item_id=item_id, item_code=item.code, item_name=item.name or item.code,
            stock_available=stock, quantity_sold=quantity_sold, net_revenue=net_revenue,
            suggested_action=_suggest_action(stock, quantity_sold),
        ))
    rows.sort(key=lambda r: r.net_revenue, reverse=True)
    return rows


# ---------------------------------------------------------------------
# تقویمِ مناسبتیِ تبلیغاتِ فروشگاهی (مناسبت‌هایِ رایجِ فروشگاهیِ ایران)
# ---------------------------------------------------------------------
SEASONAL_CALENDAR = [
    {"name": "شبِ یلدا", "jalali_month": 9, "note": "پیشنهادِ کمپین/تخفیفِ شبِ یلدا"},
    {"name": "چهارشنبه‌سوری و نوروز", "jalali_month": 12, "note": "پیشنهادِ کمپینِ تخفیفِ پایانِ سال / عیدانه"},
    {"name": "سیزده‌به‌در و فروردین", "jalali_month": 1, "note": "پیشنهادِ کمپینِ شروعِ سالِ نو"},
    {"name": "روزِ مادر", "jalali_month": 12, "note": "پیشنهادِ کمپینِ مناسبتیِ روزِ مادر (تقریبی)"},
    {"name": "بلک‌فرایدی", "jalali_month": 9, "note": "پیشنهادِ تخفیفِ ویژهٔ بلک‌فرایدی (آذرماه)"},
]


@dataclass
class UpcomingOccasion:
    name: str
    note: str
    months_away: int


def upcoming_occasions(window_months: int = 2, today: datetime.date | None = None) -> list[UpcomingOccasion]:
    """مناسبت‌هایی که ماهِ جاری یا تا window_months ماهِ بعد قرار دارند
    (چرخشی رویِ ۱۲ ماهِ شمسی)."""
    current_month = jdatetime.date.fromgregorian(date=today or datetime.date.today()).month
    result = []
    for occ in SEASONAL_CALENDAR:
        diff = (occ["jalali_month"] - current_month) % 12
        if diff <= window_months:
            result.append(UpcomingOccasion(name=occ["name"], note=occ["note"], months_away=diff))
    return sorted(result, key=lambda o: o.months_away)
