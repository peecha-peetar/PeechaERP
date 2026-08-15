"""لایهٔ سرویسِ فیلدهایِ توسعه‌یافتهٔ کاتالوگِ کالا (فازِ ۱ تا ۱۵): تامین‌کنندگانِ
کالا، رسانه/اسناد، فهرستِ موادِ اولیه (BOM)، و دارایی/استهلاک. بخشِ ۱۴
(نگاشتِ حسابِ دسته‌بندی) در inventory_engine.py است، نه این‌جا."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.inventory import (
    AssetDepreciationEntry,
    AssetDetail,
    BomHeader,
    BomLine,
    Item,
    ItemMedia,
    ItemSupplier,
)
from peecha.services import journal_entries as je_service

_Q2 = decimal.Decimal("0.01")


# ---------------------------------------------------------------------
# تامین‌کنندگانِ کالا — بخشِ ۶
# ---------------------------------------------------------------------
@dataclass
class ItemSupplierRow:
    item_supplier_id: int
    supplier_detail_account_id: int
    supplier_sku: str | None
    lead_time_days: int | None
    min_order_qty: decimal.Decimal | None
    is_preferred: bool


def list_item_suppliers(item_id: int) -> list[ItemSupplierRow]:
    with new_session() as session:
        rows = session.scalars(select(ItemSupplier).where(ItemSupplier.item_id == item_id)).all()
        return [
            ItemSupplierRow(
                r.item_supplier_id, r.supplier_detail_account_id, r.supplier_sku, r.lead_time_days,
                r.min_order_qty, r.is_preferred,
            )
            for r in rows
        ]


def add_item_supplier(
    item_id: int, supplier_detail_account_id: int, supplier_sku: str | None = None,
    lead_time_days: int | None = None, min_order_qty: decimal.Decimal | None = None,
    is_preferred: bool = False,
) -> int:
    with new_session() as session:
        existing = session.scalar(
            select(ItemSupplier).where(
                ItemSupplier.item_id == item_id, ItemSupplier.supplier_detail_account_id == supplier_detail_account_id
            )
        )
        if existing is not None:
            raise ValueError("این تامین‌کننده قبلاً برایِ این کالا ثبت شده است.")
        row = ItemSupplier(
            item_id=item_id, supplier_detail_account_id=supplier_detail_account_id,
            supplier_sku=(supplier_sku or None), lead_time_days=lead_time_days,
            min_order_qty=min_order_qty, is_preferred=is_preferred,
        )
        session.add(row)
        session.commit()
        return row.item_supplier_id


def remove_item_supplier(item_supplier_id: int, item_id: int) -> None:
    with new_session() as session:
        row = session.get(ItemSupplier, item_supplier_id)
        if row is None or row.item_id != item_id:
            raise ValueError("ردیفِ تامین‌کننده نامعتبر است.")
        session.delete(row)
        session.commit()


# ---------------------------------------------------------------------
# رسانه/اسنادِ کالا — بخشِ ۱۵
# ---------------------------------------------------------------------
_MEDIA_TYPE_CODES = ("IMAGE", "VIDEO", "CATALOG", "MANUAL", "DOCUMENT")


@dataclass
class ItemMediaRow:
    item_media_id: int
    attachment_id: int
    media_type_code: str
    alt_text: str | None
    is_primary: bool
    sort_order: int


def list_item_media(item_id: int) -> list[ItemMediaRow]:
    with new_session() as session:
        rows = session.scalars(
            select(ItemMedia).where(ItemMedia.item_id == item_id).order_by(ItemMedia.sort_order)
        ).all()
        return [
            ItemMediaRow(r.item_media_id, r.attachment_id, r.media_type_code, r.alt_text, r.is_primary, r.sort_order)
            for r in rows
        ]


def add_item_media(
    item_id: int, attachment_id: int, media_type_code: str = "IMAGE",
    alt_text: str | None = None, is_primary: bool = False,
) -> int:
    if media_type_code not in _MEDIA_TYPE_CODES:
        raise ValueError("نوعِ رسانه نامعتبر است.")
    with new_session() as session:
        row = ItemMedia(
            item_id=item_id, attachment_id=attachment_id, media_type_code=media_type_code,
            alt_text=(alt_text or None), is_primary=is_primary,
        )
        session.add(row)
        session.commit()
        return row.item_media_id


def remove_item_media(item_media_id: int, item_id: int) -> None:
    with new_session() as session:
        row = session.get(ItemMedia, item_media_id)
        if row is None or row.item_id != item_id:
            raise ValueError("ردیفِ رسانه نامعتبر است.")
        session.delete(row)
        session.commit()


# ---------------------------------------------------------------------
# فهرستِ موادِ اولیه (BOM) — بخشِ ۸، فقط برایِ نوعِ FINISHED_GOOD معنادار
# ---------------------------------------------------------------------
@dataclass
class BomLineRow:
    bom_line_id: int
    component_item_id: int
    quantity_per: decimal.Decimal
    scrap_percent: decimal.Decimal
    line_no: int


@dataclass
class BomHeaderRow:
    bom_id: int
    version_no: int
    batch_size_qty: decimal.Decimal
    production_time_minutes: int | None
    scrap_percent: decimal.Decimal
    is_active: bool


def list_boms(finished_item_id: int) -> list[BomHeaderRow]:
    with new_session() as session:
        rows = session.scalars(
            select(BomHeader).where(BomHeader.finished_item_id == finished_item_id).order_by(BomHeader.version_no)
        ).all()
        return [
            BomHeaderRow(r.bom_id, r.version_no, r.batch_size_qty, r.production_time_minutes, r.scrap_percent, r.is_active)
            for r in rows
        ]


def create_bom(
    finished_item_id: int, batch_size_qty: decimal.Decimal = decimal.Decimal(1),
    production_time_minutes: int | None = None, scrap_percent: decimal.Decimal = decimal.Decimal(0),
) -> int:
    if batch_size_qty <= 0:
        raise ValueError("اندازهٔ دسته باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        next_version = (
            session.scalar(
                select(BomHeader.version_no).where(BomHeader.finished_item_id == finished_item_id)
                .order_by(BomHeader.version_no.desc())
            )
            or 0
        ) + 1
        bom = BomHeader(
            finished_item_id=finished_item_id, version_no=next_version, batch_size_qty=batch_size_qty,
            production_time_minutes=production_time_minutes, scrap_percent=scrap_percent,
        )
        session.add(bom)
        session.commit()
        return bom.bom_id


def list_bom_lines(bom_id: int) -> list[BomLineRow]:
    with new_session() as session:
        rows = session.scalars(select(BomLine).where(BomLine.bom_id == bom_id).order_by(BomLine.line_no)).all()
        return [
            BomLineRow(r.bom_line_id, r.component_item_id, r.quantity_per, r.scrap_percent, r.line_no)
            for r in rows
        ]


def add_bom_line(
    bom_id: int, component_item_id: int, quantity_per: decimal.Decimal, scrap_percent: decimal.Decimal = decimal.Decimal(0)
) -> int:
    if quantity_per <= 0:
        raise ValueError("مقدارِ مصرفی باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        bom = session.get(BomHeader, bom_id)
        if bom is None:
            raise ValueError("فهرستِ موادِ اولیه نامعتبر است.")
        if bom.finished_item_id == component_item_id:
            raise ValueError("یک کالا نمی‌تواند جزوِ موادِ اولیهٔ خودش باشد.")
        next_no = (
            session.scalar(select(BomLine.line_no).where(BomLine.bom_id == bom_id).order_by(BomLine.line_no.desc()))
            or 0
        ) + 1
        line = BomLine(
            bom_id=bom_id, component_item_id=component_item_id, quantity_per=quantity_per,
            scrap_percent=scrap_percent, line_no=next_no,
        )
        session.add(line)
        session.commit()
        return line.bom_line_id


def remove_bom_line(bom_line_id: int, bom_id: int) -> None:
    with new_session() as session:
        row = session.get(BomLine, bom_line_id)
        if row is None or row.bom_id != bom_id:
            raise ValueError("ردیفِ فهرستِ موادِ اولیه نامعتبر است.")
        session.delete(row)
        session.commit()


# ---------------------------------------------------------------------
# دارایی/استهلاک — بخشِ ۱۳، فقط برایِ نوعِ ASSET معنادار
# ---------------------------------------------------------------------
_DEPRECIATION_METHOD_CODES = ("STRAIGHT_LINE", "DECLINING_BALANCE")


@dataclass
class AssetDetailRow:
    item_id: int
    asset_tag_no: str | None
    depreciation_group_code: str | None
    useful_life_months: int
    depreciation_method_code: str
    acquisition_date: datetime.date
    acquisition_cost: decimal.Decimal
    salvage_value: decimal.Decimal


def get_asset_detail(item_id: int) -> AssetDetailRow | None:
    with new_session() as session:
        row = session.get(AssetDetail, item_id)
        if row is None:
            return None
        return AssetDetailRow(
            row.item_id, row.asset_tag_no, row.depreciation_group_code, row.useful_life_months,
            row.depreciation_method_code, row.acquisition_date, row.acquisition_cost, row.salvage_value,
        )


def set_asset_detail(
    item_id: int, useful_life_months: int, acquisition_date: datetime.date, acquisition_cost: decimal.Decimal,
    depreciation_method_code: str = "STRAIGHT_LINE", asset_tag_no: str | None = None,
    depreciation_group_code: str | None = None, salvage_value: decimal.Decimal = decimal.Decimal(0),
) -> None:
    if depreciation_method_code not in _DEPRECIATION_METHOD_CODES:
        raise ValueError("روشِ استهلاک نامعتبر است.")
    if useful_life_months <= 0:
        raise ValueError("عمرِ مفید باید بزرگ‌تر از صفر باشد.")
    with new_session() as session:
        row = session.get(AssetDetail, item_id)
        if row is None:
            row = AssetDetail(item_id=item_id)
            session.add(row)
        row.asset_tag_no = asset_tag_no or None
        row.depreciation_group_code = depreciation_group_code or None
        row.useful_life_months = useful_life_months
        row.depreciation_method_code = depreciation_method_code
        row.acquisition_date = acquisition_date
        row.acquisition_cost = acquisition_cost
        row.salvage_value = salvage_value
        session.commit()


def _accumulated_depreciation(session, item_id: int) -> decimal.Decimal:
    rows = session.scalars(
        select(AssetDepreciationEntry.depreciation_amount).where(AssetDepreciationEntry.item_id == item_id)
    ).all()
    return sum(rows, decimal.Decimal(0))


def post_monthly_depreciation(
    item_id: int, company_id: int, posted_by_user_id: int, period_date: datetime.date,
    depreciation_expense_account_id: int, accumulated_depreciation_account_id: int,
) -> int:
    with new_session() as session:
        asset = session.get(AssetDetail, item_id)
        if asset is None:
            raise ValueError("این کالا دارایی نیست یا اطلاعاتِ دارایی هنوز ثبت نشده است.")
        if session.scalar(
            select(AssetDepreciationEntry).where(
                AssetDepreciationEntry.item_id == item_id, AssetDepreciationEntry.period_date == period_date
            )
        ) is not None:
            raise ValueError("استهلاکِ این دوره قبلاً ثبت شده است.")
        depreciable_base = asset.acquisition_cost - asset.salvage_value
        accumulated = _accumulated_depreciation(session, item_id)
        remaining = depreciable_base - accumulated
        if remaining <= 0:
            raise ValueError("این دارایی به‌طورِ کامل مستهلک شده است.")
        if asset.depreciation_method_code == "STRAIGHT_LINE":
            monthly_amount = depreciable_base / asset.useful_life_months
        else:
            rate = decimal.Decimal(2) / asset.useful_life_months
            monthly_amount = (depreciable_base - accumulated) * rate
        monthly_amount = min(monthly_amount, remaining).quantize(_Q2, rounding=decimal.ROUND_HALF_UP)
        if monthly_amount <= 0:
            raise ValueError("مبلغِ استهلاکِ این دوره صفر است.")

        item = session.get(Item, item_id)
        item_name = item.notes or f"دارایی #{item_id}" if item is not None else f"دارایی #{item_id}"

    je_result = je_service.create_journal_entry(
        company_id, posted_by_user_id, period_date, f"استهلاکِ ماهانهٔ دارایی — {item_name}",
        [
            je_service.LineInput(
                account_id=depreciation_expense_account_id, description="هزینهٔ استهلاک",
                debit=monthly_amount, credit=decimal.Decimal(0),
            ),
            je_service.LineInput(
                account_id=accumulated_depreciation_account_id, description="استهلاکِ انباشته",
                debit=decimal.Decimal(0), credit=monthly_amount,
            ),
        ],
        entry_type_code="INVENTORY",
    )

    with new_session() as session:
        entry = AssetDepreciationEntry(
            item_id=item_id, period_date=period_date, depreciation_amount=monthly_amount,
            journal_entry_id=je_result.journal_entry_id,
        )
        session.add(entry)
        session.commit()
        return entry.depreciation_entry_id


def list_depreciation_entries(item_id: int) -> list[tuple[datetime.date, decimal.Decimal]]:
    with new_session() as session:
        rows = session.scalars(
            select(AssetDepreciationEntry).where(AssetDepreciationEntry.item_id == item_id)
            .order_by(AssetDepreciationEntry.period_date)
        ).all()
        return [(r.period_date, r.depreciation_amount) for r in rows]
