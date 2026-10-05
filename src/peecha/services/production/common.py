"""هستهٔ مشترکِ تولید -- R266: تنظیمات، برچسب‌ها، نقش‌هایِ حساب، سندِ حسابداری و Audit.

قاعده: ثبتِ مالی فقط از موتورِ سندِ موجود (journal_entries.create_journal_entry) و حرکتِ موجودی فقط از موتورِ انبار
(inventory_engine.post_stock_document)؛ هر دو در همان تراکنشِ عملیاتِ تولید (session) تا یا همه بنشینند یا هیچ‌کدام.
حساب‌ها نقش‌محورند و در همان «نگاشتِ حسابِ انبار» (inv.account_mappings) تعریف می‌شوند.
"""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.inventory import InventoryAccountMapping, Item
from peecha.db.models.production import ProductionSettings

ZERO = decimal.Decimal(0)
ONE = decimal.Decimal(1)
_Q2 = decimal.Decimal("0.01")
_Q6 = decimal.Decimal("0.000001")
ENTRY_TYPE = "PRODUCTION"

# نقش‌هایِ حسابِ تولید (کلیدِ inv.account_mappings)
WIP = "PRODUCTION_WIP"
LABOR_APPLIED = "PRODUCTION_LABOR_APPLIED"
MACHINE_APPLIED = "PRODUCTION_MACHINE_APPLIED"
OVERHEAD_APPLIED = "PRODUCTION_OVERHEAD_APPLIED"
VARIANCE = "PRODUCTION_VARIANCE"
SCRAP_LOSS = "PRODUCTION_SCRAP_LOSS"
ROLE_LABELS = {
    WIP: "کالایِ در جریانِ ساخت (WIP)",
    LABOR_APPLIED: "دستمزدِ جذب‌شدهٔ تولید",
    MACHINE_APPLIED: "هزینهٔ ماشینِ جذب‌شدهٔ تولید",
    OVERHEAD_APPLIED: "سربارِ جذب‌شدهٔ تولید",
    VARIANCE: "انحرافِ بهایِ تولید",
    SCRAP_LOSS: "زیانِ ضایعاتِ غیرعادیِ تولید",
}

COMPONENT_TYPES = {"MATERIAL": "مادهٔ اولیه", "PACKAGING": "بسته‌بندی", "PART": "قطعه", "SEMI_FINISHED": "نیمه‌ساخته",
                   "CONSUMABLE": "مصرفی"}
OUTPUT_TYPES = {"MAIN": "محصولِ اصلی", "BY_PRODUCT": "محصولِ جانبی", "CO_PRODUCT": "محصولِ مشترک"}
CENTER_TYPES = {"LINE": "خطِ تولید", "ASSEMBLY": "مونتاژ", "MACHINING": "ماشین‌کاری", "PAINT": "رنگ", "QC": "کنترلِ کیفیت",
                "PACKING": "بسته‌بندی", "OTHER": "سایر"}
OVERHEAD_BASES = {"LABOR_HOURS": "ساعتِ کارِ مستقیم", "MACHINE_HOURS": "ساعتِ ماشین", "QUANTITY": "مقدارِ تولید",
                  "MATERIAL_COST": "بهایِ مواد", "LABOR_COST": "هزینهٔ دستمزد", "PERCENTAGE": "درصد", "MANUAL": "دستی"}
JOINT_METHODS = {"QUANTITY": "مقدار", "WEIGHT": "وزن", "SALES_VALUE": "ارزشِ فروش", "NRV": "خالصِ ارزشِ بازیافتنی",
                 "PERCENTAGE": "درصدِ دستی", "MANUAL": "مبلغِ دستی"}
BOM_STATUS = {"DRAFT": "پیش‌نویس", "ACTIVE": "فعال", "ARCHIVED": "بایگانی"}

SETTING_FIELDS = (
    "default_material_warehouse_id", "default_production_warehouse_id", "default_fg_warehouse_id",
    "default_scrap_warehouse_id", "default_cost_center_detail_account_id", "auto_reservation", "auto_consumption",
    "allow_over_consumption", "allow_under_consumption", "auto_cost_calculation", "require_cost_closing",
    "allow_negative_material", "shortage_policy", "require_cost_center", "default_overhead_basis",
    "default_joint_cost_method", "abnormal_scrap_percent", "order_prefix",
)


def money(value) -> decimal.Decimal:
    return decimal.Decimal(value or 0).quantize(_Q2, rounding=decimal.ROUND_HALF_UP)


def qty(value) -> decimal.Decimal:
    return decimal.Decimal(value or 0).quantize(_Q6, rounding=decimal.ROUND_HALF_UP)


def dec(value) -> decimal.Decimal:
    return decimal.Decimal(str(value)) if value is not None and not isinstance(value, decimal.Decimal) else (value or ZERO)


# --- تنظیمات -----------------------------------------------------------------------------
def settings(session, company_id: int) -> ProductionSettings:
    row = session.get(ProductionSettings, company_id)
    if row is None:
        row = ProductionSettings(company_id=company_id, auto_reservation=True, auto_consumption=False,
                                 allow_over_consumption=True, allow_under_consumption=True, auto_cost_calculation=True,
                                 require_cost_closing=False, allow_negative_material=False, shortage_policy="WARN",
                                 require_cost_center=False, default_overhead_basis="LABOR_HOURS",
                                 default_joint_cost_method="QUANTITY", abnormal_scrap_percent=decimal.Decimal(5),
                                 order_prefix="PO")
        session.add(row)
        session.flush()
    return row


def get_settings(company_id: int) -> ProductionSettings:
    with new_session() as session:
        row = settings(session, company_id)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def update_settings(company_id: int, user_id: int | None = None, **fields) -> None:
    with new_session() as session:
        row = settings(session, company_id)
        changes = {}
        for key, value in fields.items():
            if key not in SETTING_FIELDS:
                raise ValueError(f"تنظیمِ نامعتبر: {key}")
            if key == "shortage_policy" and value not in ("WARN", "BLOCK"):
                raise ValueError("سیاستِ کمبودِ مواد نامعتبر است.")
            if key == "default_overhead_basis" and value not in OVERHEAD_BASES:
                raise ValueError("مبنایِ سربارِ نامعتبر.")
            if key == "default_joint_cost_method" and value not in JOINT_METHODS:
                raise ValueError("روشِ تخصیصِ تولیدِ مشترکِ نامعتبر.")
            if getattr(row, key) != value:
                changes[key] = [str(getattr(row, key)), str(value)]
                setattr(row, key, value)
        row.updated_at = datetime.datetime.now()
        if changes:
            audit(session, company_id, user_id, "ProductionSettings", company_id, "SETTINGS", changes)
        session.commit()


# --- حساب‌ها --------------------------------------------------------------------------------
def role_account(session, company_id: int, role: str) -> int | None:
    row = session.get(InventoryAccountMapping, (company_id, role))
    return row.account_id if row is not None else None


def missing_roles(company_id: int, roles: tuple[str, ...]) -> list[str]:
    with new_session() as session:
        return [ROLE_LABELS.get(r, r) for r in roles if role_account(session, company_id, r) is None]


def require_roles(session, company_id: int, roles: tuple[str, ...]) -> None:
    missing = [ROLE_LABELS.get(r, r) for r in roles if role_account(session, company_id, r) is None]
    if missing:
        raise ValueError("نگاشتِ حسابِ تولید ناقص است (تنظیماتِ انبار ← نگاشتِ حساب‌ها): " + "، ".join(missing))


def post_journal(session, company_id: int, user_id: int, date: datetime.date, description: str,
                 lines: list[tuple[str, decimal.Decimal, decimal.Decimal, tuple[int | None, ...]]]) -> int | None:
    """سندِ حسابداریِ تولید در همان تراکنش. هر ردیف: (نقش، بدهکار، بستانکار، تفصیلی‌ها)؛ ردیف‌هایِ هم‌حساب تجمیع می‌شوند."""
    from peecha.services import journal_entries as je_service

    merged: dict[tuple, decimal.Decimal] = {}
    for role, debit, credit, details in lines:
        account_id = role_account(session, company_id, role)
        if account_id is None:
            raise ValueError(f"حسابِ «{ROLE_LABELS.get(role, role)}» در نگاشتِ حساب‌هایِ انبار تعیین نشده است.")
        mapping = session.get(InventoryAccountMapping, (company_id, role))
        ids = {d for d in details if d}
        if mapping is not None and mapping.detail_account_id:
            ids.add(mapping.detail_account_id)
        key = (account_id, tuple(sorted(ids)))
        merged[key] = merged.get(key, ZERO) + money(debit) - money(credit)
    all_ids = {d for k in merged for d in k[1]}
    dim_of = dict(session.execute(select(DetailAccount.detail_account_id, DetailAccount.dimension_type_id)
                                  .where(DetailAccount.detail_account_id.in_(all_ids))).all()) if all_ids else {}
    inputs = []
    for (account_id, details), net in merged.items():
        if net == 0:
            continue
        inputs.append(je_service.LineInput(
            account_id=account_id, description=description, debit=net if net > 0 else ZERO, credit=-net if net < 0 else ZERO,
            details={dim_of[d]: d for d in details if d in dim_of}))
    if not inputs:
        return None
    return je_service.create_journal_entry(company_id, user_id, date, description, inputs, entry_type_code=ENTRY_TYPE,
                                           session=session).journal_entry_id


# --- Audit / ابزار -------------------------------------------------------------------------
def audit(session, company_id: int, user_id: int | None, entity_type: str, entity_id: int, operation: str,
          changes: dict) -> None:
    """Audit با سرویسِ موجود؛ نامِ عملیاتِ تولید در changes.operation."""
    from peecha.services import audit as audit_service

    action = operation if operation in ("CREATE", "DELETE") else "UPDATE"
    audit_service.log_activity(session, company_id=company_id, user_id=user_id, entity_type=entity_type,
                               entity_id=entity_id, action=action,
                               changes={"operation": operation, **{k: v if isinstance(v, (list, dict, int, bool)) or v is None
                                                                    else str(v) for k, v in changes.items()}})


def item_of(session, company_id: int, item_id: int) -> Item:
    item = session.get(Item, item_id)
    if item is None or item.company_id != company_id:
        raise ValueError("کالا نامعتبر است.")
    return item


def item_label(session, item_id: int) -> str:
    from peecha.db.models.accounting import DetailAccount as DA

    row = session.execute(select(DA.code, DA.name).join(Item, Item.item_detail_account_id == DA.detail_account_id)
                          .where(Item.item_id == item_id)).first()
    return f"{row[0]} {row[1]}" if row else str(item_id)


def item_labels(session, item_ids) -> dict[int, str]:
    ids = list({i for i in item_ids if i})
    if not ids:
        return {}
    return {iid: f"{code} {name}" for iid, code, name in session.execute(
        select(Item.item_id, DetailAccount.code, DetailAccount.name)
        .join(DetailAccount, DetailAccount.detail_account_id == Item.item_detail_account_id).where(Item.item_id.in_(ids))).all()}


def factor(session, item_id: int, uom_id: int | None) -> decimal.Decimal:
    """ضریبِ تبدیلِ واحد به واحدِ پایهٔ کالا -- از همان تعریفِ واحدهایِ کالا (inv.item_uom_conversions)."""
    from peecha.db.models.inventory import ItemUomConversion

    if uom_id is None:
        return ONE
    item = session.get(Item, item_id)
    if item is None or uom_id == item.base_uom_id:
        return ONE
    row = session.scalar(select(ItemUomConversion).where(ItemUomConversion.item_id == item_id,
                                                         ItemUomConversion.uom_id == uom_id))
    if row is None:
        raise ValueError("برایِ این واحد، تبدیل به واحدِ پایهٔ کالا در فرمِ کالا تعریف نشده است.")
    return decimal.Decimal(row.conversion_factor)
