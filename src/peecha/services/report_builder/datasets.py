"""R374: مجموعه‌داده‌های گزارش‌ساز. هر مجموعه ستون‌های ثابت، فرم‌هایی که مجوز «مشاهده»ی یکی‌شان برای استفاده لازم است،
ستون تاریخ (برای محدود کردن بازه در خود پایگاه داده) و تابع خواندن دارد. پرس‌وجوها ثابت همین فایل‌اند و شرکت و شعبه‌های
مجاز کاربر همیشه اعمال می‌شود."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import func, select

from peecha.db.base import new_session

TEXT, DATE, MONEY, QTY, INT = "TEXT", "DATE", "MONEY", "QTY", "INT"
NUMERIC = (MONEY, QTY, INT)
MAX_ROWS = 200_000
ZERO = decimal.Decimal(0)


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str
    additive: bool = True   # جمع ستونی معنا دارد (بهای واحد و اولویت ندارند)


@dataclass(frozen=True)
class Dataset:
    code: str
    label: str
    forms: tuple[str, ...]
    columns: tuple[Column, ...]
    date_key: str | None
    fetch: Callable[[int, int, datetime.date | None, datetime.date | None], list[dict]]
    description: str = ""

    def column(self, key: str) -> Column | None:
        return next((c for c in self.columns if c.key == key), None)


def _branches(company_id: int, user_id: int):
    from peecha.services import branch_access

    return branch_access.allowed_branch_ids(company_id, user_id)


def _item_info(session, item_ids) -> dict[int, tuple[str, str, str]]:
    """(کد، نام، گروه) هر کالا."""
    from peecha.db.models.accounting import DetailAccount
    from peecha.db.models.inventory import Item, ItemCategory

    ids = list({i for i in item_ids if i})
    if not ids:
        return {}
    rows = session.execute(select(Item.item_id, DetailAccount.code, DetailAccount.name, ItemCategory.name)
                           .join(DetailAccount, DetailAccount.detail_account_id == Item.item_detail_account_id)
                           .outerjoin(ItemCategory, ItemCategory.category_id == Item.category_id)
                           .where(Item.item_id.in_(ids))).all()
    return {i: (code or "", name or "", cat or "") for i, code, name, cat in rows}


def _names(session, model, key, ids, *cols) -> dict:
    ids = list({i for i in ids if i})
    if not ids:
        return {}
    return {r[0]: " — ".join(str(x) for x in r[1:] if x) for r in session.execute(
        select(key, *cols).where(key.in_(ids))).all()}


def _commercial(types: dict[str, tuple[str, int]], party_label: str) -> Callable:
    def fetch(company_id: int, user_id: int, date_from, date_to) -> list[dict]:
        from peecha.db.models.accounting import DetailAccount
        from peecha.db.models.commercial import Branch, CommercialDocument as CD, CommercialDocumentLine as CL
        from peecha.db.models.inventory import Warehouse

        q = (select(CD.document_type_code, CD.document_no, CD.document_date, CD.counterparty_detail_account_id, CD.branch_id,
                    CD.warehouse_id, CL.warehouse_id, CL.item_id, CL.quantity_base, CL.quantity, CL.unit_price, CL.discount_amount,
                    CL.tax_amount, CL.line_total)
             .join(CL, CL.document_id == CD.document_id)
             .where(CD.company_id == company_id, CD.document_type_code.in_(list(types)), CD.status_code.notin_(("DRAFT", "CANCELLED"))))
        if date_from:
            q = q.where(CD.document_date >= date_from)
        if date_to:
            q = q.where(CD.document_date <= date_to)
        allowed = _branches(company_id, user_id)
        if allowed is not None:
            q = q.where(CD.branch_id.in_(allowed) | CD.branch_id.is_(None))
        with new_session() as session:
            rows = session.execute(q.order_by(CD.document_date, CD.document_no, CL.line_no).limit(MAX_ROWS + 1)).all()
            items = _item_info(session, [r[7] for r in rows])
            parties = _names(session, DetailAccount, DetailAccount.detail_account_id, [r[3] for r in rows], DetailAccount.code,
                             DetailAccount.name)
            branches = _names(session, Branch, Branch.branch_id, [r[4] for r in rows], Branch.name)
            warehouses = _names(session, Warehouse, Warehouse.warehouse_id, [r[6] or r[5] for r in rows], Warehouse.name)
        out = []
        for t, no, when, party, branch, head_wh, line_wh, item, qty_base, qty, price, discount, tax, total in rows:
            label, sign = types[t]
            code, name, group = items.get(item, ("", "", ""))
            net = (decimal.Decimal(qty) * decimal.Decimal(price) - decimal.Decimal(discount or 0)).quantize(decimal.Decimal("0.01"))
            out.append({"date": when, "doc_type": label, "doc_no": str(no), "party": parties.get(party, ""), "item_code": code,
                        "item_name": name, "item_group": group, "warehouse": warehouses.get(line_wh or head_wh, ""),
                        "branch": branches.get(branch, ""), "quantity": sign * decimal.Decimal(qty_base),
                        "unit_price": decimal.Decimal(price), "discount": sign * decimal.Decimal(discount or 0),
                        "net_amount": sign * net, "tax": sign * decimal.Decimal(tax or 0), "total": sign * decimal.Decimal(total or 0)})
        return out

    return fetch


def _commercial_columns(party_label: str) -> tuple[Column, ...]:
    return (Column("date", "تاریخ", DATE), Column("doc_type", "نوع سند", TEXT), Column("doc_no", "شمارهٔ سند", TEXT),
            Column("party", party_label, TEXT), Column("item_code", "کد کالا", TEXT), Column("item_name", "نام کالا", TEXT),
            Column("item_group", "گروه کالا", TEXT), Column("warehouse", "انبار", TEXT), Column("branch", "شعبه", TEXT),
            Column("quantity", "مقدار (واحد اصلی)", QTY), Column("unit_price", "بهای واحد", MONEY, False), Column("discount", "تخفیف", MONEY),
            Column("net_amount", "مبلغ پس از تخفیف", MONEY), Column("tax", "مالیات و عوارض", MONEY), Column("total", "مبلغ کل", MONEY))


def _stock(company_id: int, user_id: int, date_from, date_to) -> list[dict]:
    from peecha.db.models.inventory import StockBalance, Warehouse

    allowed = _branches(company_id, user_id)
    q = (select(StockBalance.item_id, StockBalance.warehouse_id, func.sum(StockBalance.quantity_on_hand),
                func.sum(StockBalance.quantity_reserved), func.sum(StockBalance.quantity_on_hand * StockBalance.average_unit_cost))
         .join(Warehouse, Warehouse.warehouse_id == StockBalance.warehouse_id)
         .where(StockBalance.company_id == company_id).group_by(StockBalance.item_id, StockBalance.warehouse_id))
    if allowed is not None:
        q = q.where(Warehouse.branch_id.in_(allowed) | Warehouse.branch_id.is_(None))
    with new_session() as session:
        rows = session.execute(q.limit(MAX_ROWS + 1)).all()
        items = _item_info(session, [r[0] for r in rows])
        warehouses = _names(session, Warehouse, Warehouse.warehouse_id, [r[1] for r in rows], Warehouse.name)
    out = []
    for item, wh, on_hand, reserved, value in rows:
        on_hand, reserved, value = decimal.Decimal(on_hand or 0), decimal.Decimal(reserved or 0), decimal.Decimal(value or 0)
        if not on_hand and not reserved:
            continue
        code, name, group = items.get(item, ("", "", ""))
        out.append({"item_code": code, "item_name": name, "item_group": group, "warehouse": warehouses.get(wh, ""),
                    "on_hand": on_hand, "reserved": reserved, "free": on_hand - reserved,
                    "avg_cost": (value / on_hand).quantize(decimal.Decimal("0.01")) if on_hand else ZERO,
                    "value": value.quantize(decimal.Decimal("0.01"))})
    return out


_JE_STATUS = {"TEMPORARY": "موقت", "PERMANENT": "دائم", "REVERSED": "برگشت‌خورده", "DRAFT": "پیش‌نویس"}


def _journal(company_id: int, user_id: int, date_from, date_to) -> list[dict]:
    from peecha.db.models.accounting import (
        ChartOfAccount, DetailAccount, JournalEntry, JournalEntryLine, JournalEntryLineDetail, JournalEntryStatus,
    )
    from peecha.db.models.core import Translation

    q = (select(JournalEntry.document_date, JournalEntry.temporary_no, JournalEntry.permanent_no, JournalEntryStatus.code,
                JournalEntry.description, JournalEntryLine.line_id, JournalEntryLine.account_id, JournalEntryLine.description,
                JournalEntryLine.debit_amount_base, JournalEntryLine.credit_amount_base)
         .join(JournalEntry, JournalEntry.journal_entry_id == JournalEntryLine.journal_entry_id)
         .join(JournalEntryStatus, JournalEntryStatus.status_id == JournalEntry.status_id)
         .where(JournalEntry.company_id == company_id, JournalEntryStatus.code != "CANCELLED"))
    if date_from:
        q = q.where(JournalEntry.document_date >= date_from)
    if date_to:
        q = q.where(JournalEntry.document_date <= date_to)
    with new_session() as session:
        rows = session.execute(q.order_by(JournalEntry.document_date, JournalEntry.temporary_no, JournalEntryLine.line_no)
                               .limit(MAX_ROWS + 1)).all()
        account_ids = list({r[6] for r in rows})
        codes = dict(session.execute(select(ChartOfAccount.account_id, ChartOfAccount.full_code)
                                     .where(ChartOfAccount.account_id.in_(account_ids or [0]))).all())
        names = dict(session.execute(select(Translation.entity_id, Translation.value).where(
            Translation.entity_type == "ChartOfAccount", Translation.property_name == "Name",
            Translation.entity_id.in_(account_ids or [0]))).all())
        details: dict[int, list[str]] = {}
        line_ids = [r[5] for r in rows]
        for i in range(0, len(line_ids), 5000):
            for line_id, code, name in session.execute(
                    select(JournalEntryLineDetail.line_id, DetailAccount.code, DetailAccount.name)
                    .join(DetailAccount, DetailAccount.detail_account_id == JournalEntryLineDetail.detail_account_id)
                    .where(JournalEntryLineDetail.line_id.in_(line_ids[i:i + 5000]))).all():
                details.setdefault(line_id, []).append(f"{code} {name or ''}".strip())
    return [{"date": when, "temp_no": str(temp), "perm_no": str(perm) if perm else "", "status": _JE_STATUS.get(status, status),
             "account_code": codes.get(acc, ""), "account_name": names.get(acc, ""), "details": "، ".join(details.get(line, [])),
             "description": line_desc or entry_desc or "", "debit": decimal.Decimal(debit or 0), "credit": decimal.Decimal(credit or 0),
             "balance": decimal.Decimal(debit or 0) - decimal.Decimal(credit or 0)}
            for when, temp, perm, status, entry_desc, line, acc, line_desc, debit, credit in rows]


def _production(company_id: int, user_id: int, date_from, date_to) -> list[dict]:
    from peecha.db.models.production import ProductionOrder
    from peecha.services.production.orders import STATUS_LABELS

    q = select(ProductionOrder).where(ProductionOrder.company_id == company_id)
    if date_from:
        q = q.where(ProductionOrder.start_date >= date_from)
    if date_to:
        q = q.where(ProductionOrder.start_date <= date_to)
    with new_session() as session:
        orders = list(session.scalars(q.order_by(ProductionOrder.start_date, ProductionOrder.order_id).limit(MAX_ROWS + 1)))
        items = _item_info(session, [o.item_id for o in orders])
        out = []
        for o in orders:
            code, name, group = items.get(o.item_id, ("", "", ""))
            planned, remaining = decimal.Decimal(o.planned_qty or 0), decimal.Decimal(o.remaining_qty or 0)
            out.append({"order_code": o.order_code, "item_code": code, "item_name": name, "item_group": group,
                        "status": STATUS_LABELS.get(o.status_code, o.status_code), "priority": int(o.priority or 0),
                        "start_date": o.start_date, "due_date": o.due_date, "planned_qty": planned, "remaining_qty": remaining,
                        "done_qty": planned - remaining, "late_days": max(0, (datetime.date.today() - o.due_date).days)
                        if o.due_date and remaining > 0 and o.status_code not in ("CLOSED", "CANCELLED", "COMPLETED") else 0})
    return out


_SALES_FORMS = ("commercial_documents_list_sales", "commercial_document_sales_invoice")
_PURCHASE_FORMS = ("commercial_documents_list_purchase", "commercial_document_purchase_invoice")

DATASETS: dict[str, Dataset] = {d.code: d for d in (
    Dataset("sales_lines", "ردیف‌های فروش", _SALES_FORMS, _commercial_columns("مشتری"), "date",
            _commercial({"SALES_INVOICE": ("فاکتور فروش", 1), "SALES_RETURN": ("برگشت از فروش", -1)}, "مشتری"),
            "ردیف‌های فاکتور فروش و برگشت از فروش (برگشت با علامت منفی)؛ پیش‌نویس و ابطال‌شده حساب نمی‌شود."),
    Dataset("purchase_lines", "ردیف‌های خرید", _PURCHASE_FORMS, _commercial_columns("تامین‌کننده"), "date",
            _commercial({"PURCHASE_INVOICE": ("فاکتور خرید", 1), "PURCHASE_RETURN": ("برگشت به تامین‌کننده", -1)}, "تامین‌کننده"),
            "ردیف‌های فاکتور خرید و برگشت به تامین‌کننده (برگشت با علامت منفی)."),
    Dataset("stock", "موجودی کالا", ("warehouse_report_stock_on_hand", "inventory_documents_list"), (
        Column("item_code", "کد کالا", TEXT), Column("item_name", "نام کالا", TEXT), Column("item_group", "گروه کالا", TEXT),
        Column("warehouse", "انبار", TEXT), Column("on_hand", "موجودی", QTY), Column("reserved", "رزرو", QTY),
        Column("free", "آزاد", QTY), Column("avg_cost", "میانگین بها", MONEY, False), Column("value", "ارزش موجودی", MONEY)), None, _stock,
            "موجودی لحظه‌ای هر کالا در هر انبار."),
    Dataset("journal_lines", "ردیف‌های اسناد حسابداری", ("journal_entries_list", "journal_entry"), (
        Column("date", "تاریخ", DATE), Column("temp_no", "شمارهٔ موقت", TEXT), Column("perm_no", "شمارهٔ دائم", TEXT),
        Column("status", "وضعیت سند", TEXT), Column("account_code", "کد حساب", TEXT), Column("account_name", "نام حساب", TEXT),
        Column("details", "تفصیلی‌ها", TEXT), Column("description", "شرح", TEXT), Column("debit", "بدهکار", MONEY),
        Column("credit", "بستانکار", MONEY), Column("balance", "مانده (بدهکار منهای بستانکار)", MONEY)), "date", _journal,
            "ردیف‌های همهٔ اسناد حسابداری جز ابطال‌شده، به ارز پایه."),
    Dataset("production_orders", "دستورهای تولید", ("prd_orders",), (
        Column("order_code", "شمارهٔ دستور", TEXT), Column("item_code", "کد کالا", TEXT), Column("item_name", "نام کالا", TEXT),
        Column("item_group", "گروه کالا", TEXT), Column("status", "وضعیت", TEXT), Column("priority", "اولویت", INT, False),
        Column("start_date", "تاریخ شروع", DATE), Column("due_date", "موعد", DATE), Column("planned_qty", "مقدار برنامه", QTY),
        Column("done_qty", "تولیدشده", QTY), Column("remaining_qty", "مانده", QTY), Column("late_days", "دیرکرد (روز)", INT, False)),
            "start_date", _production, "دستورهای تولید با مقدار برنامه، تولیدشده و مانده."),
)}

