"""اصلاحِ ماندهٔ ریالیِ موجودی (تسعیر/پاک‌سازی) -- R230.

وقتی موجودیِ تعدادیِ یک کالا صفر است ولی حسابِ «موجودیِ کالا» در دفترِ کل (به
تفکیکِ تفصیلیِ همان کالا) هنوز مانده دارد، آن مانده انحرافِ بهاست (گرد‌کردن،
اختلافِ بهایِ امانی/اصلاحیه، برگشت‌ها). روشِ استاندارد: این مانده با یک سندِ
اصلاحی به حسابِ «اختلافِ بهایِ موجودی» (یا بهایِ تمام‌شده) بسته می‌شود تا
ارزشِ دفتریِ موجودی با موجودیِ واقعی (صفر) برابر شود.

حسابِ مقابل از نگاشتِ INVENTORY_REVALUATION (تنظیماتِ انبار ‹ نگاشتِ حساب‌ها)؛
اگر تعریف نشده باشد INVENTORY_COST_VARIANCE و در نهایت COGS استفاده می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    DetailAccount, JournalEntry, JournalEntryLine, JournalEntryLineDetail, JournalEntryStatus,
)
from peecha.db.models.inventory import Item, StockBalance
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_engine as engine_service
from peecha.services import journal_entries as je_service

_ZERO = decimal.Decimal(0)
_COUNTER_KEYS = ("INVENTORY_REVALUATION", "INVENTORY_COST_VARIANCE", "COGS")


@dataclass
class ResidualRow:
    item_id: int
    item_detail_account_id: int
    item_label: str
    quantity_on_hand: decimal.Decimal
    stock_value: decimal.Decimal
    ledger_balance: decimal.Decimal

    @property
    def residual(self) -> decimal.Decimal:
        return self.ledger_balance - self.stock_value


def counter_account_id(company_id: int) -> tuple[int | None, str | None]:
    for key in _COUNTER_KEYS:
        account_id = engine_service.get_account_mapping(company_id, key)
        if account_id is not None:
            return account_id, key
    return None, None


def inventory_account_tracks_items(company_id: int) -> bool:
    """بدونِ تفصیلیِ «کالا» رویِ حسابِ موجودی، مانده به تفکیکِ کالا قابلِ‌محاسبه نیست."""
    inventory_account_id = engine_service.get_account_mapping(company_id, "INVENTORY_ASSET")
    if inventory_account_id is None:
        return False
    item_dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)
    return engine_service_requires_item(inventory_account_id, item_dim_type_id)


def list_residuals(company_id: int, zero_quantity_only: bool = True, threshold: decimal.Decimal = decimal.Decimal("0.01")) -> list[ResidualRow]:
    inventory_account_id = engine_service.get_account_mapping(company_id, "INVENTORY_ASSET")
    if inventory_account_id is None:
        return []
    item_dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)
    with new_session() as session:
        ledger = dict(session.execute(
            select(
                JournalEntryLineDetail.detail_account_id,
                func.sum(JournalEntryLine.debit_amount_base - JournalEntryLine.credit_amount_base),
            )
            .join(JournalEntryLine, JournalEntryLine.line_id == JournalEntryLineDetail.line_id)
            .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
            .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
            .where(
                JournalEntry.company_id == company_id, JournalEntryLine.account_id == inventory_account_id,
                JournalEntryLineDetail.dimension_type_id == item_dim_type_id,
                JournalEntryStatus.code.notin_(("DRAFT", "CANCELLED")),  # سندِ برگشتی و برگشتش هر دو حساب می‌شوند
            )
            .group_by(JournalEntryLineDetail.detail_account_id)
        ).all())
        stock = {
            item_id: (qty or _ZERO, value or _ZERO)
            for item_id, qty, value in session.execute(
                select(StockBalance.item_id, func.sum(StockBalance.quantity_on_hand), func.sum(StockBalance.total_value))
                .where(StockBalance.company_id == company_id).group_by(StockBalance.item_id)
            ).all()
        }
        items = session.execute(
            select(Item.item_id, Item.item_detail_account_id, DetailAccount.code, DetailAccount.name)
            .join(DetailAccount, DetailAccount.detail_account_id == Item.item_detail_account_id)
            .where(Item.company_id == company_id)
        ).all()
    rows = []
    for item_id, detail_id, code, name in items:
        balance = ledger.get(detail_id, _ZERO) or _ZERO
        qty, value = stock.get(item_id, (_ZERO, _ZERO))
        if zero_quantity_only and qty != 0:
            continue
        row = ResidualRow(item_id, detail_id, f"{code} — {name or ''}", qty, value, balance)
        if abs(row.residual) >= threshold:
            rows.append(row)
    return rows


def required_extra_dimensions(company_id: int) -> list[dimensions_service.RequiredDimension]:
    """R231: ابعادِ الزامیِ حسابِ موجودی و حسابِ مقابل (به‌جز «کالا» که خودکار
    پر می‌شود) -- مثلاً مرکزِ هزینه/پروژه -- تا در فرمِ تسعیر انتخاب شوند."""
    item_dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)
    counter_id, key = counter_account_id(company_id)
    fixed = engine_service.get_account_mapping_detail(company_id, key) if key else None
    fixed_dim = None
    if fixed is not None:
        with new_session() as session:
            row = session.get(DetailAccount, fixed)
            fixed_dim = row.dimension_type_id if row is not None else None
    seen: dict[int, dimensions_service.RequiredDimension] = {}
    for account_id in (engine_service.get_account_mapping(company_id, "INVENTORY_ASSET"), counter_id):
        if account_id is None:
            continue
        for dim in dimensions_service.get_required_dimensions_for_account(account_id):
            if dim.dimension_type_id not in (item_dim_type_id, fixed_dim):
                seen.setdefault(dim.dimension_type_id, dim)
    return list(seen.values())


def post_residual_adjustment(
    company_id: int, user_id: int, item_ids: list[int], document_date: datetime.date | None = None,
    extra_details: dict[int, int] | None = None,
) -> int:
    """سندِ اصلاحی: ماندهٔ دفتریِ موجودیِ کالاهایِ انتخاب‌شده به حسابِ مقابل بسته می‌شود.
    extra_details: تفصیلی‌هایِ الزامیِ دیگر (مرکزِ هزینه/پروژه...)، {نوعِ‌بُعد: تفصیلی}."""
    from peecha.services.commercial_documents import auto_line

    rows = [r for r in list_residuals(company_id) if r.item_id in set(item_ids)]
    if not rows:
        raise ValueError("ماندهٔ ریالیِ قابلِ‌اصلاحی برایِ کالاهایِ انتخاب‌شده وجود ندارد.")
    counter_id, key = counter_account_id(company_id)
    if counter_id is None:
        raise ValueError(
            "حسابِ «اختلافِ بهایِ موجودی (تسعیر)» در تنظیماتِ انبار ‹ نگاشتِ حساب‌ها مشخص نشده است."
        )
    fixed_detail = engine_service.get_account_mapping_detail(company_id, key)
    inventory_account_id = engine_service.get_account_mapping(company_id, "INVENTORY_ASSET")
    item_dim_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.INVENTORY_ITEM_CODE)
    dims = {k: v for k, v in (extra_details or {}).items() if v is not None}
    description = "اصلاحِ ماندهٔ ریالیِ موجودیِ کالایِ با موجودیِ صفر (تسعیر)"
    lines: list[je_service.LineInput] = []
    for r in rows:
        amount = abs(r.residual).quantize(decimal.Decimal("0.01"))
        if not amount:
            continue
        positive = r.residual > 0  # دفترِ کل بیشتر از واقعیت -> بستانکارِ موجودی
        item = (item_dim_type_id, r.item_detail_account_id)
        lines.append(auto_line(
            inventory_account_id, f"{description} -- {r.item_label}",
            _ZERO if positive else amount, amount if positive else _ZERO, dims, item=item,
        ))
        lines.append(auto_line(
            counter_id, f"{description} -- {r.item_label}",
            amount if positive else _ZERO, _ZERO if positive else amount, dims, item=item,
            fixed_detail_account_id=fixed_detail,
        ))
    result = je_service.create_journal_entry(
        company_id, user_id, document_date or datetime.date.today(), description, lines, entry_type_code="COMMERCIAL",
    )
    return result.journal_entry_id


def engine_service_requires_item(account_id: int, item_dim_type_id: int) -> bool:
    from peecha.services.commercial_documents import _account_requires_dimension

    return _account_requires_dimension(account_id, item_dim_type_id)
