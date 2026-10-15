"""قالب ستون‌ها و اعتبارسنجی هر ماژول افتتاحیه (R314).

هر ماژول: ستون‌ها (کلید، برچسب، الزامی، نوع، راهنما)، کلید طبیعی ردیف (برای جلوگیری از تکرار و بارگذاری دوباره) و
اعتبارسنجی که کدها را به شناسهٔ PeechaERP نگاشت می‌کند و خطا را به تفکیک ستون برمی‌گرداند. ثبت نهایی در posting.py
و فقط با سرویس رسمی همان ماژول است.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

from sqlalchemy import func, select

from peecha.services.opening import common as c


@dataclass
class Column:
    key: str
    label: str
    required: bool = False
    kind: str = "text"  # text | decimal | date | choice
    help: str = ""
    choices: dict[str, str] | None = None  # مقدار قابل‌قبول (فارسی یا کد) ← کد


@dataclass
class Check:
    resolved: dict = field(default_factory=dict)
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    amount: decimal.Decimal = c.ZERO

    def err(self, col: str, msg: str) -> None:
        self.errors.append((col, msg))

    def warn(self, col: str, msg: str) -> None:
        self.warnings.append((col, msg))


_YES = {"بله": True, "آری": True, "yes": True, "y": True, "1": True, "true": True, "خیر": False, "نه": False, "no": False,
        "n": False, "0": False, "false": False}


# --- جست‌وجوی کد ← شناسه (یک بار در هر بارگذاری) -------------------------------------------------------------
class Lookups:
    def __init__(self, session, company_id: int, run) -> None:
        self.s, self.company_id, self.run = session, company_id, run
        self._cache: dict[str, object] = {}

    def _once(self, name: str, fn):
        if name not in self._cache:
            self._cache[name] = fn()
        return self._cache[name]

    # حساب و تفصیلی
    def accounts(self) -> dict:
        from peecha.db.models.accounting import ChartOfAccount

        return self._once("acc", lambda: {a.full_code: a for a in self.s.scalars(select(ChartOfAccount).where(
            ChartOfAccount.company_id == self.company_id))})

    def account(self, code: str):
        """کد کامل (1-11-111)، همان بدون جداکننده (111111) یا کد معین اگر یکتا باشد (111)؛ اول بین حساب‌های معین."""
        def index(accs):
            out = []
            for keyf in (lambda a: a.full_code, lambda a: _plain(a.full_code), lambda a: a.segment_code):
                groups: dict[str, list] = {}
                for a in accs:
                    groups.setdefault(keyf(a), []).append(a)
                out.append({k: v[0] for k, v in groups.items() if len(v) == 1})
            return out

        def load():
            accs = list(self.accounts().values())
            return index([a for a in accs if a.is_postable]), index(accs)
        code = (code or "").strip()
        for full, plain, seg in self._once("accidx", load):
            hit = full.get(code) or plain.get(_plain(code)) or seg.get(code)
            if hit is not None:
                return hit
        return None

    def account_by_id(self, account_id: int):
        return next((a for a in self.accounts().values() if a.account_id == account_id), None)

    def dim_types(self) -> dict:
        from peecha.db.models.accounting import DetailDimensionType

        return self._once("dims", lambda: {d.code: d.dimension_type_id for d in self.s.scalars(select(DetailDimensionType).where(
            DetailDimensionType.company_id == self.company_id))})

    def details(self) -> dict:
        from peecha.db.models.accounting import DetailAccount

        return self._once("det", lambda: {(d.dimension_type_id, d.code): d for d in self.s.scalars(select(DetailAccount).where(
            DetailAccount.company_id == self.company_id))})

    def detail(self, dim_code: str, code: str):
        type_id = self.dim_types().get(dim_code)
        return self.details().get((type_id, code)) if type_id else None

    def required_dims(self, account_id: int) -> set[int]:
        from peecha.db.models.accounting import AccountDetailDimension

        req = self._once("req", lambda: {})
        if account_id not in req:
            req[account_id] = set(self.s.scalars(select(AccountDetailDimension.dimension_type_id).where(
                AccountDetailDimension.account_id == account_id, AccountDetailDimension.is_required.is_(True))))
        return req[account_id]

    def person_groups(self, account_id: int) -> set[int]:
        from peecha.db.models.accounting import AccountPersonGroup

        groups = self._once("pgroups", lambda: {})
        if account_id not in groups:
            groups[account_id] = set(self.s.scalars(select(AccountPersonGroup.person_group_id).where(
                AccountPersonGroup.account_id == account_id)))
        return groups[account_id]

    def dim_label(self, type_id: int) -> str:
        from peecha.services import detail_dimensions as dims

        code = {v: k for k, v in self.dim_types().items()}.get(type_id, "")
        return "شخص" if code == dims.PERSON_DIMENSION_CODE else dims.SPECIALIZED_DIMENSION_LABELS.get(code, code)

    def currencies(self) -> dict:
        from peecha.db.models.core import CompanyCurrency, Currency

        def load():
            enabled = set(self.s.scalars(select(CompanyCurrency.currency_id).where(
                CompanyCurrency.company_id == self.company_id, CompanyCurrency.is_active.is_(True))))
            return {cur.iso_code.upper(): (cur.currency_id, cur.currency_id in enabled) for cur in self.s.scalars(select(Currency))}
        return self._once("cur", load)

    def currency(self, chk: Check, col: str, code: str, rate_col: str, rate) -> tuple[int, decimal.Decimal]:
        """(شناسهٔ ارز، نرخ). خالی = ارز پایهٔ فرایند با نرخ ۱."""
        base = self.run.currency_id
        if not code:
            return base, decimal.Decimal(1)
        hit = self.currencies().get(code.upper())
        if hit is None:
            chk.err(col, f"ارز «{code}» تعریف نشده است")
            return base, decimal.Decimal(1)
        cur_id, enabled = hit
        if not enabled and cur_id != base:
            chk.err(col, f"ارز «{code}» برای این شرکت فعال نیست")
        if cur_id == base:
            return base, decimal.Decimal(1)
        if rate is None or rate <= 0:
            chk.err(rate_col, "برای ارز غیرپایه نرخ تبدیل مورد تأیید الزامی است")
            return cur_id, decimal.Decimal(1)
        return cur_id, rate

    # انبار و کالا
    def warehouses(self) -> dict:
        from peecha.db.models.inventory import Warehouse

        return self._once("wh", lambda: {w.code: w for w in self.s.scalars(select(Warehouse).where(
            Warehouse.company_id == self.company_id))})

    def items(self) -> dict:
        """کد کالا ← ItemRow (کد متغیر یا کد تفصیلی کالا، همان که در سندها دیده می‌شود)."""
        from peecha.services import inventory_catalog

        return self._once("items", lambda: {i.code: i for i in inventory_catalog.list_items(self.company_id)})

    def uoms(self) -> dict:
        from peecha.db.models.inventory import Uom

        def load():
            out = {}
            for u in self.s.scalars(select(Uom).where((Uom.company_id == self.company_id) | Uom.company_id.is_(None))):
                out.setdefault(u.code, u)
                out.setdefault(u.name, u)
            return out
        return self._once("uom", load)

    def uom_factor(self, item, uom) -> decimal.Decimal | None:
        from peecha.db.models.inventory import ItemUomConversion

        if uom.uom_id == item.base_uom_id:
            return decimal.Decimal(1)
        conv = self.s.scalar(select(ItemUomConversion.conversion_factor).where(
            ItemUomConversion.item_id == item.item_id, ItemUomConversion.uom_id == uom.uom_id))
        return c.dec(conv) if conv else None

    def bin(self, warehouse_id: int, code: str):
        from peecha.db.models.inventory import BinLocation

        return self.s.scalar(select(BinLocation).where(BinLocation.warehouse_id == warehouse_id,
                                                       (BinLocation.code == code) | (BinLocation.location_code == code)))

    def branches(self) -> dict:
        from peecha.db.models.commercial import Branch

        return self._once("br", lambda: {b.code: b for b in self.s.scalars(select(Branch).where(Branch.company_id == self.company_id))})

    def inv_mapping(self, key: str) -> int | None:
        from peecha.db.models.inventory import InventoryAccountMapping

        maps = self._once("invmap", lambda: {})
        if key not in maps:
            row = self.s.get(InventoryAccountMapping, (self.company_id, key))
            maps[key] = row.account_id if row is not None else None
        return maps[key]

    def control_accounts(self) -> dict[int, str]:
        """حساب‌هایی که زیرسیستم‌های همین فرایند پر می‌کنند ← نام ماژول."""
        from peecha.services.opening import reconcile

        return self._once("ctrl", lambda: reconcile.control_accounts(self.s, self.company_id, self.run.run_id))


def _plain(code: str) -> str:
    return "".join(ch for ch in (code or "") if ch.isalnum())


def _detail_code(lk: Lookups, chk: Check, col: str, dim_code: str, code: str, out: dict) -> None:
    if not code:
        return
    d = lk.detail(dim_code, code)
    if d is None:
        chk.err(col, f"کد «{code}» پیدا نشد")
    elif not d.is_active:
        chk.err(col, f"«{code}» غیرفعال است")
    else:
        out[d.dimension_type_id] = d.detail_account_id


def _person(lk: Lookups, chk: Check, col: str, code: str):
    d = lk.detail("PERSON", code)
    if d is None:
        chk.err(col, f"طرف‌حساب با کد «{code}» پیدا نشد")
        return None
    if not d.is_active:
        chk.err(col, f"طرف‌حساب «{code}» غیرفعال است")
    return d


# =========================================================================================================
class Handler:
    code = ""
    columns: list[Column] = []

    def key(self, v: dict, lk: Lookups | None = None) -> str:
        raise NotImplementedError

    def validate(self, lk: Lookups, v: dict) -> Check:
        raise NotImplementedError


class GLHandler(Handler):
    """تراز افتتاحیه: ماندهٔ همهٔ حساب‌ها (کل تراز، شامل حساب‌های کنترل زیرسیستم‌ها)."""
    code = "GL"
    columns = [
        Column("account_code", "کد حساب معین", True, help="کد کامل حساب قابل ثبت، مثل 1101"),
        Column("debit", "بدهکار", kind="decimal", help="به ارز ردیف؛ یکی از بدهکار یا بستانکار"),
        Column("credit", "بستانکار", kind="decimal"),
        Column("person_code", "کد تفصیلی شخص"),
        Column("cost_center_code", "کد مرکز هزینه"),
        Column("project_code", "کد پروژه"),
        Column("other_details", "تفصیلی‌های دیگر", help="به شکل نوع:کد، جداشده با ویرگول؛ مثل BANK_ACCOUNT:B01"),
        Column("currency_code", "ارز", help="خالی = ارز پایه؛ مثل USD"),
        Column("exchange_rate", "نرخ تبدیل", kind="decimal"),
        Column("description", "شرح"),
    ]

    def _details(self, lk: Lookups, chk: Check, v: dict) -> dict[int, int]:
        out: dict[int, int] = {}
        _detail_code(lk, chk, "person_code", "PERSON", v["person_code"], out)
        _detail_code(lk, chk, "cost_center_code", "COST_CENTER", v["cost_center_code"], out)
        _detail_code(lk, chk, "project_code", "PROJECT", v["project_code"], out)
        for part in (v["other_details"] or "").replace("،", ",").split(","):
            part = part.strip()
            if not part:
                continue
            if ":" not in part:
                chk.err("other_details", f"«{part}» باید به شکل نوع:کد باشد")
                continue
            dim, code = (x.strip() for x in part.split(":", 1))
            if dim.upper() not in lk.dim_types():
                chk.err("other_details", f"نوع تفصیلی «{dim}» تعریف نشده است")
                continue
            _detail_code(lk, chk, "other_details", dim.upper(), code, out)
        return out

    def key(self, v: dict, lk: Lookups | None = None) -> str:
        acc = lk.account(v["account_code"]) if lk is not None else None
        return "|".join([acc.full_code if acc is not None else v["account_code"], v["person_code"], v["cost_center_code"], v["project_code"],
                         ",".join(sorted(x.strip() for x in (v["other_details"] or "").replace("،", ",").split(",") if x.strip())),
                         (v["currency_code"] or "").upper()])

    def validate(self, lk: Lookups, v: dict) -> Check:
        chk = Check()
        acc = lk.account(v["account_code"])
        if acc is None:
            chk.err("account_code", f"حساب «{v['account_code']}» در کدینگ این شرکت نیست")
        elif not acc.is_postable:
            chk.err("account_code", "فقط حساب معین (قابل ثبت) پذیرفته می‌شود")
        elif not acc.is_active:
            chk.err("account_code", "حساب غیرفعال است")
        debit, credit = v["debit"] or c.ZERO, v["credit"] or c.ZERO
        if debit < 0 or credit < 0:
            chk.err("debit" if debit < 0 else "credit", "مبلغ منفی پذیرفته نمی‌شود؛ ستون مقابل را پر کنید")
        if (debit > 0) == (credit > 0):
            chk.err("debit", "هر ردیف یا بدهکار دارد یا بستانکار، نه هر دو و نه هیچ‌کدام")
        details = self._details(lk, chk, v)
        cur_id, rate = lk.currency(chk, "currency_code", v["currency_code"], "exchange_rate", v["exchange_rate"])
        if acc is not None and not chk.errors:
            clearing = c.clearing_account_id(lk.company_id)
            if acc.account_id == clearing:
                chk.err("account_code", "حساب واسط افتتاحیه در تراز وارد نمی‌شود")
            missing = lk.required_dims(acc.account_id) - set(details)
            if missing:
                chk.err("account_code", "تفصیلی الزامی این حساب خالی است: " + "، ".join(lk.dim_label(t) for t in sorted(missing)))
            allowed = lk.person_groups(acc.account_id)
            person = lk.detail("PERSON", v["person_code"]) if v["person_code"] else None
            if allowed and person is not None and person.person_group_id not in allowed:
                chk.err("person_code", "این شخص در گروه‌های مجاز این حساب نیست")
            if acc.currency_id is not None and acc.currency_id != cur_id:
                chk.err("currency_code", "این حساب فقط با ارز تعریف‌شدهٔ خودش ثبت می‌شود")
            module = lk.control_accounts().get(acc.account_id)
            if module:
                chk.warn("account_code", f"حساب کنترل «{c.MODULE_LABELS[module]}»: ماندهٔ آن از زیرسیستم ثبت و با همین رقم تطبیق "
                                         "داده می‌شود؛ در سند دفتر کل به حساب واسط می‌رود")
        base_debit, base_credit = c.money(debit * rate), c.money(credit * rate)
        chk.resolved = {"account_id": acc.account_id if acc else None, "details": {str(k): d for k, d in details.items()},
                        "currency_id": cur_id, "rate": str(rate), "debit": str(debit), "credit": str(credit),
                        "base_debit": str(base_debit), "base_credit": str(base_credit), "description": v["description"]}
        chk.amount = base_debit - base_credit
        return chk


_QUALITY = {"سالم": "OK", "ok": "OK", "قرنطینه": "QUARANTINE", "quarantine": "QUARANTINE", "مردود": "REJECTED",
            "rejected": "REJECTED", "آسیب‌دیده": "DAMAGED", "damaged": "DAMAGED", "مسدود": "BLOCKED", "blocked": "BLOCKED"}


class InventoryHandler(Handler):
    """موجودی کالا به تفکیک انبار، محل، بچ و سریال با بهای واحد معتبر."""
    code = "INVENTORY"
    columns = [
        Column("warehouse_code", "کد انبار", True),
        Column("item_code", "کد کالا", True),
        Column("quantity", "مقدار", True, "decimal"),
        Column("unit_cost", "بهای واحد", True, "decimal", "بهای هر واحد همان ستون «واحد»؛ بهای ساختگی وارد نکنید"),
        Column("uom_code", "واحد", help="خالی = واحد پایهٔ کالا"),
        Column("bin_code", "کد محل", help="فقط برای انبار دارای محل"),
        Column("batch_no", "شمارهٔ بچ"),
        Column("serial_no", "شمارهٔ سریال", help="برای کالای سریالی، هر سریال یک ردیف با مقدار ۱"),
        Column("expiry_date", "تاریخ انقضا", kind="date"),
        Column("manufacture_date", "تاریخ تولید", kind="date"),
        Column("quality_status", "وضعیت کیفیت", kind="choice", choices=_QUALITY,
               help="سالم، قرنطینه، مردود، آسیب‌دیده یا مسدود؛ غیر سالم فقط در انبار قرنطینه/ضایعات"),
        Column("currency_code", "ارز بها"),
        Column("exchange_rate", "نرخ تبدیل", kind="decimal"),
        Column("description", "شرح"),
    ]

    def key(self, v: dict, lk: Lookups | None = None) -> str:
        return "|".join([v["warehouse_code"], v["item_code"], v["bin_code"], v["batch_no"], v["serial_no"]])

    def validate(self, lk: Lookups, v: dict) -> Check:
        chk = Check()
        wh = lk.warehouses().get(v["warehouse_code"])
        if wh is None:
            chk.err("warehouse_code", f"انبار «{v['warehouse_code']}» تعریف نشده است")
        elif not wh.is_active:
            chk.err("warehouse_code", "انبار غیرفعال است")
        item = lk.items().get(v["item_code"])
        if item is None:
            chk.err("item_code", f"کالای «{v['item_code']}» تعریف نشده است")
        else:
            if not item.is_active:
                chk.err("item_code", "کالا غیرفعال است")
            if not item.is_stock_tracked or item.item_kind_code == "SERVICE":
                chk.err("item_code", "این کالا موجودی انبار ندارد (خدمت یا بدون کنترل موجودی)")
            if item.has_variants:
                chk.err("item_code", "کالای اصلی متغیردار موجودی ندارد؛ کد متغیر را وارد کنید")
        qty, cost = v["quantity"], v["unit_cost"]
        if qty is not None and qty <= 0:
            chk.err("quantity", "مقدار باید بزرگ‌تر از صفر باشد")
        if cost is None:
            chk.err("unit_cost", "بهای واحد مشخص نیست؛ بهای واقعی سیستم قبلی را وارد کنید")
        elif cost < 0:
            chk.err("unit_cost", "بهای منفی پذیرفته نمی‌شود")
        elif cost == 0:
            chk.warn("unit_cost", "بهای صفر؛ اگر واقعاً کالای بی‌بهاست ادامه دهید")
        factor = decimal.Decimal(1)
        uom_id = item.base_uom_id if item else None
        if item is not None and v["uom_code"]:
            uom = lk.uoms().get(v["uom_code"])
            if uom is None:
                chk.err("uom_code", f"واحد «{v['uom_code']}» تعریف نشده است")
            else:
                f = lk.uom_factor(item, uom)
                if f is None:
                    chk.err("uom_code", "این واحد برای این کالا تعریف نشده است")
                else:
                    factor, uom_id = f, uom.uom_id
        bin_id = None
        if wh is not None and v["bin_code"]:
            b = lk.bin(wh.warehouse_id, v["bin_code"])
            if b is None:
                chk.err("bin_code", f"محل «{v['bin_code']}» در این انبار نیست")
            elif not b.is_active:
                chk.err("bin_code", "محل غیرفعال است")
            else:
                bin_id = b.bin_location_id
        if item is not None:
            if item.track_batch and not v["batch_no"]:
                chk.err("batch_no", "این کالا بچ‌محور است؛ شمارهٔ بچ الزامی است")
            if item.track_expiry and not v["expiry_date"]:
                chk.err("expiry_date", "این کالا تاریخ انقضا دارد؛ الزامی است")
            if item.track_serial:
                if not v["serial_no"]:
                    chk.err("serial_no", "کالای سریالی: برای هر سریال یک ردیف با مقدار ۱ وارد کنید")
                elif qty is not None and qty * factor != 1:
                    chk.err("quantity", "ردیف سریالی باید دقیقاً یک واحد پایه باشد")
            elif v["serial_no"]:
                chk.err("serial_no", "این کالا سریالی نیست")
            if v["batch_no"] and not item.track_batch:
                chk.warn("batch_no", "این کالا بچ‌محور نیست؛ شمارهٔ بچ نادیده گرفته می‌شود")
        if v["expiry_date"] and v["expiry_date"] <= lk.run.balance_date:
            chk.warn("expiry_date", "کالا در تاریخ برش منقضی شده است")
        quality = v["quality_status"] or "OK"
        from peecha.services import stock_controls

        if wh is not None:
            special = wh.warehouse_type_code in stock_controls.DISPOSAL_WAREHOUSE_TYPES
            if quality != "OK" and not special:
                chk.err("quality_status", "کالای قرنطینه/مردود/آسیب‌دیده فقط در انبار قرنطینه یا ضایعات وارد می‌شود")
            if special and quality == "OK":
                chk.warn("warehouse_code", "انبار قرنطینه/ضایعات است؛ این موجودی بدون تصمیم مجاز قابل تخصیص نیست")
        cur_id, rate = lk.currency(chk, "currency_code", v["currency_code"], "exchange_rate", v["exchange_rate"])
        qty_base = (qty or c.ZERO) * factor
        unit_base = ((cost or c.ZERO) * rate / factor) if factor else c.ZERO
        chk.resolved = {"warehouse_id": wh.warehouse_id if wh else None, "item_id": item.item_id if item else None,
                        "uom_id": uom_id, "factor": str(factor), "quantity": str(qty or 0), "quantity_base": str(qty_base),
                        "unit_cost_base": str(unit_base), "bin_location_id": bin_id, "batch_no": v["batch_no"] or None,
                        "serial_no": v["serial_no"] or None, "expiry_date": v["expiry_date"], "manufacture_date": v["manufacture_date"],
                        "quality_status": quality, "currency_id": cur_id, "rate": str(rate),
                        "item_detail_account_id": item.item_detail_account_id if item else None}
        chk.amount = c.money((qty or c.ZERO) * (cost or c.ZERO) * rate)
        return chk


class OpenItemsHandler(Handler):
    """اسناد باز دریافتنی/پرداختنی: هر فاکتور یا سند تسویه‌نشدهٔ سیستم قبلی."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.receivable = code == "RECEIVABLES"
        party = "مشتری" if self.receivable else "تامین‌کننده"
        self.columns = [
            Column("counterparty_code", f"کد تفصیلی {party}", True),
            Column("legacy_no", "شمارهٔ سند در سیستم قبلی", True),
            Column("legacy_type", "نوع سند قبلی", help="مثلاً فاکتور، اعلامیه یا سند حسابداری"),
            Column("doc_date", "تاریخ سند", True, "date"),
            Column("due_date", "سررسید", kind="date"),
            Column("original_amount", "مبلغ اصلی", True, "decimal"),
            Column("settled_amount", "تسویه‌شده تا برش", kind="decimal"),
            Column("open_amount", "ماندهٔ باز", kind="decimal", help="اختیاری؛ اگر پر شود باید برابر «اصلی − تسویه‌شده» باشد"),
            Column("currency_code", "ارز"),
            Column("exchange_rate", "نرخ تبدیل", kind="decimal"),
            Column("branch_code", "کد شعبه"),
            Column("cost_center_code", "کد مرکز هزینه"),
            Column("project_code", "کد پروژه"),
            Column("disputed", "مورد اختلاف", kind="choice", choices=_YES, help="بله/خیر"),
            Column("description", "شرح"),
        ]

    def key(self, v: dict, lk: Lookups | None = None) -> str:
        return f"{v['counterparty_code']}|{v['legacy_no']}"

    def validate(self, lk: Lookups, v: dict) -> Check:
        from peecha.db.models.commercial import CustomerProfile, SupplierProfile

        chk = Check()
        party = _person(lk, chk, "counterparty_code", v["counterparty_code"])
        if party is not None:
            profile = CustomerProfile if self.receivable else SupplierProfile
            if lk.s.get(profile, party.detail_account_id) is None:
                chk.warn("counterparty_code", "این شخص پروندهٔ " + ("مشتری" if self.receivable else "تامین‌کننده") +
                         " ندارد؛ سررسید پیش‌فرض و سقف اعتبار برایش محاسبه نمی‌شود")
        original, settled = v["original_amount"], v["settled_amount"] or c.ZERO
        if original is not None and original <= 0:
            chk.err("original_amount", "مبلغ اصلی باید مثبت باشد")
        if settled < 0:
            chk.err("settled_amount", "مبلغ تسویه منفی پذیرفته نمی‌شود")
        open_amount = (original or c.ZERO) - settled
        if original is not None and open_amount <= 0:
            chk.err("settled_amount", "این سند کاملاً تسویه شده است؛ اسناد تسویه‌شده منتقل نمی‌شوند")
        if v["open_amount"] is not None and original is not None and c.money(v["open_amount"]) != c.money(open_amount):
            chk.err("open_amount", "ماندهٔ باز با «مبلغ اصلی − تسویه‌شده» برابر نیست")
        if v["doc_date"] and v["doc_date"] > lk.run.balance_date:
            chk.err("doc_date", "تاریخ سند بعد از تاریخ مانده‌هاست؛ سند بعد از برش در سیستم جدید ثبت می‌شود")
        if v["due_date"] and v["doc_date"] and v["due_date"] < v["doc_date"]:
            chk.err("due_date", "سررسید پیش از تاریخ سند است")
        cur_id, rate = lk.currency(chk, "currency_code", v["currency_code"], "exchange_rate", v["exchange_rate"])
        dims: dict[int, int] = {}
        _detail_code(lk, chk, "cost_center_code", "COST_CENTER", v["cost_center_code"], dims)
        _detail_code(lk, chk, "project_code", "PROJECT", v["project_code"], dims)
        branch = lk.branches().get(v["branch_code"]) if v["branch_code"] else None
        if v["branch_code"] and branch is None:
            chk.err("branch_code", f"شعبهٔ «{v['branch_code']}» تعریف نشده است")
        if v["disputed"]:
            chk.warn("disputed", "مورد اختلاف: منتقل می‌شود و در گزارش افتتاحیه علامت می‌خورد")
        cc_type, pj_type = lk.dim_types().get("COST_CENTER"), lk.dim_types().get("PROJECT")
        role = "CUSTOMER_RECEIVABLE" if self.receivable else "SUPPLIER_PAYABLE"
        ctrl = lk.inv_mapping(role)
        if ctrl is None:
            chk.err("counterparty_code", f"حساب «{'دریافتنی مشتریان' if self.receivable else 'پرداختنی تامین‌کنندگان'}» "
                                         "در تنظیمات انبار نگاشت نشده است")
        elif party is not None:
            missing = lk.required_dims(ctrl) - {lk.dim_types().get("PERSON"), *dims}
            if missing:
                chk.err("counterparty_code", "حساب کنترل این مانده، این تفصیلی‌ها را هم لازم دارد: "
                        + "، ".join(lk.dim_label(t) for t in sorted(missing)))
            groups = lk.person_groups(ctrl)
            if groups and party.person_group_id not in groups:
                chk.err("counterparty_code", "این شخص در گروه‌های مجاز حساب کنترل نیست")
        chk.resolved = {"counterparty_id": party.detail_account_id if party else None, "account_id": ctrl,
                        "currency_id": cur_id, "rate": str(rate),
                        "original": str(original or 0), "settled": str(settled), "open": str(open_amount),
                        "open_base": str(c.money(open_amount * rate)), "doc_date": v["doc_date"], "due_date": v["due_date"],
                        "branch_id": branch.branch_id if branch else None, "cost_center_id": dims.get(cc_type),
                        "project_id": dims.get(pj_type), "legacy_no": v["legacy_no"], "legacy_type": v["legacy_type"],
                        "disputed": bool(v["disputed"]), "description": v["description"]}
        chk.amount = c.money(open_amount * rate)
        return chk


_CHEQUE_KIND = {"دریافتی": "RECEIVED", "received": "RECEIVED", "پرداختی": "ISSUED", "issued": "ISSUED"}


class ChequesHandler(Handler):
    """چک‌های دریافتی نزد صندوق و چک‌های پرداختی وصول‌نشده."""
    code = "CHEQUES"
    columns = [
        Column("kind", "نوع چک", True, "choice", "دریافتی یا پرداختی", _CHEQUE_KIND),
        Column("cheque_no", "شمارهٔ چک", True),
        Column("due_date", "سررسید", True, "date"),
        Column("amount", "مبلغ", True, "decimal"),
        Column("counterparty_code", "کد تفصیلی طرف‌حساب", True),
        Column("holder_code", "کد صندوق/حساب بانکی", help="دریافتی: صندوق نگه‌دارندهٔ چک؛ پرداختی: حساب بانکی صادرکننده"),
        Column("bank_name", "بانک"),
        Column("sayad_no", "شمارهٔ صیاد/سری"),
        Column("party_name", "نام صادرکننده/گیرنده"),
        Column("description", "شرح"),
    ]

    def key(self, v: dict, lk: Lookups | None = None) -> str:
        return f"{v['kind']}|{v['cheque_no']}|{v['counterparty_code']}"

    def validate(self, lk: Lookups, v: dict) -> Check:
        from peecha.db.models.treasury import IssuedCheck, ReceivedCheck
        from peecha.services import commercial_settlements as settlements

        chk = Check()
        kind = v["kind"]
        party = _person(lk, chk, "counterparty_code", v["counterparty_code"])
        if v["amount"] is not None and v["amount"] <= 0:
            chk.err("amount", "مبلغ چک باید مثبت باشد")
        direction = "RECEIPT" if kind == "RECEIVED" else "PAYMENT"
        account_id, options = settlements.resolve_method_detail_options(lk.company_id, direction, "CHECK")
        if account_id is None:
            chk.err("kind", f"حساب «{'چک‌های دریافتنی' if kind == 'RECEIVED' else 'چک‌های پرداختنی'}» در تنظیمات خزانه نگاشت نشده است")
        holder = None
        restricted = bool(account_id and lk.required_dims(account_id))
        if v["holder_code"]:
            holder = next((o for o in options if getattr(o, "code", None) == v["holder_code"]), None)
            if holder is None and not restricted:
                holder = lk.detail("BANK_ACCOUNT" if kind == "ISSUED" else "CASH_BOX", v["holder_code"])
            if holder is None:
                chk.err("holder_code", f"«{v['holder_code']}» جزو صندوق‌ها/حساب‌های بانکی مجاز این چک نیست")
        elif kind == "ISSUED":
            chk.err("holder_code", "برای چک پرداختی حساب بانکی صادرکننده الزامی است")
        elif restricted:
            chk.err("holder_code", "حساب چک‌های دریافتنی، صندوق نگه‌دارنده را الزامی کرده است")
        model = ReceivedCheck if kind == "RECEIVED" else IssuedCheck
        if v["cheque_no"] and lk.s.scalar(select(func.count()).select_from(model).where(
                model.company_id == lk.company_id, model.check_no == v["cheque_no"],
                model.counterparty_detail_account_id == (party.detail_account_id if party else None))):
            chk.err("cheque_no", "این چک برای همین طرف‌حساب قبلاً در خزانه ثبت شده است")
        if v["due_date"] and v["due_date"] < lk.run.balance_date - datetime.timedelta(days=365 * 3):
            chk.warn("due_date", "سررسید بیش از سه سال پیش است؛ از باز بودن چک مطمئن شوید")
        chk.resolved = {"kind": kind, "counterparty_id": party.detail_account_id if party else None,
                        "holder_id": getattr(holder, "detail_account_id", None), "account_id": account_id,
                        "amount": str(v["amount"] or 0), "due_date": v["due_date"], "cheque_no": v["cheque_no"],
                        "bank_name": v["bank_name"] or None, "sayad_no": v["sayad_no"] or None, "party_name": v["party_name"] or None,
                        "description": v["description"]}
        chk.amount = c.money(v["amount"] or 0)
        return chk


_FA_METHOD = {"خط مستقیم": "STRAIGHT_LINE", "straight_line": "STRAIGHT_LINE", "نزولی": "DECLINING_BALANCE",
              "declining_balance": "DECLINING_BALANCE", "بدون استهلاک": "NONE", "none": "NONE"}
_FA_STATUS = {"در حال بهره‌برداری": "IN_SERVICE", "in_service": "IN_SERVICE", "در تعمیر": "UNDER_MAINTENANCE",
              "under_maintenance": "UNDER_MAINTENANCE", "معلق": "SUSPENDED", "suspended": "SUSPENDED"}


class FixedAssetsHandler(Handler):
    """دارایی موجود با بهای تمام‌شده، استهلاک انباشته تا برش و عمر باقی‌مانده."""
    code = "FIXED_ASSETS"
    columns = [
        Column("asset_code", "کد دارایی", True),
        Column("name", "نام دارایی", True),
        Column("category_code", "کد طبقه", True),
        Column("cost", "بهای تمام‌شده", True, "decimal"),
        Column("accumulated_depreciation", "استهلاک انباشته تا برش", kind="decimal"),
        Column("book_value", "ارزش دفتری", kind="decimal", help="اختیاری؛ اگر پر شود باید «بها − استهلاک انباشته» باشد"),
        Column("acquisition_date", "تاریخ خرید", kind="date"),
        Column("depreciation_start_date", "تاریخ شروع استهلاک/بهره‌برداری", kind="date"),
        Column("method", "روش استهلاک", kind="choice", choices=_FA_METHOD, help="خالی = پیش‌فرض طبقه"),
        Column("useful_life_months", "عمر مفید (ماه)", kind="decimal", help="خالی = پیش‌فرض طبقه"),
        Column("elapsed_months", "ماه‌های مستهلک‌شده تا برش", kind="decimal",
               help="خالی = از تاریخ شروع استهلاک تا تاریخ مانده‌ها"),
        Column("residual_value", "ارزش اسقاط", kind="decimal"),
        Column("serial_no", "شمارهٔ سریال"),
        Column("location_code", "کد محل استقرار"),
        Column("cost_center_code", "کد مرکز هزینه"),
        Column("project_code", "کد پروژه"),
        Column("branch_code", "کد شعبه"),
        Column("status", "وضعیت", kind="choice", choices=_FA_STATUS, help="خالی = در حال بهره‌برداری"),
    ]

    def key(self, v: dict, lk: Lookups | None = None) -> str:
        return v["asset_code"]

    def validate(self, lk: Lookups, v: dict) -> Check:
        from peecha.db.models.fixed_assets import Asset, AssetCategory, AssetLocation, AssetSettings
        from peecha.services.fixed_assets import common as fc

        chk = Check()
        if lk.s.scalar(select(func.count()).select_from(Asset).where(Asset.company_id == lk.company_id,
                                                                     Asset.asset_code == v["asset_code"])):
            chk.err("asset_code", "دارایی با این کد در سیستم هست؛ دارایی افتتاحیه دوباره ثبت نمی‌شود")
        cat = lk.s.scalar(select(AssetCategory).where(AssetCategory.company_id == lk.company_id,
                                                      AssetCategory.code == v["category_code"]))
        if cat is None:
            chk.err("category_code", f"طبقهٔ «{v['category_code']}» تعریف نشده است")
        else:
            missing = fc.missing_accounts(cat, ("asset_account_id", "accumulated_depreciation_account_id"))
            if missing:
                chk.err("category_code", "حساب‌های این طبقه کامل نیست: " + "، ".join(missing))
        cost, accum = v["cost"], v["accumulated_depreciation"] or c.ZERO
        residual = v["residual_value"] or c.ZERO
        if cost is not None and cost <= 0:
            chk.err("cost", "بهای تمام‌شده باید مثبت باشد")
        if accum < 0:
            chk.err("accumulated_depreciation", "استهلاک انباشته منفی پذیرفته نمی‌شود")
        if cost is not None and accum > cost:
            chk.err("accumulated_depreciation", "استهلاک انباشته از بهای تمام‌شده بیشتر است")
        if v["book_value"] is not None and cost is not None and c.money(v["book_value"]) != c.money(cost - accum):
            chk.err("book_value", "ارزش دفتری با «بها − استهلاک انباشته» برابر نیست")
        method = v["method"] or (cat.default_method if cat else "STRAIGHT_LINE")
        life = v["useful_life_months"] if v["useful_life_months"] is not None else (
            decimal.Decimal(cat.default_life_months) if cat and cat.default_life_months else None)
        start = v["depreciation_start_date"]
        if method != "NONE":
            if start is None:
                chk.err("depreciation_start_date", "تاریخ شروع استهلاک الزامی است")
            if not life or life <= 0:
                chk.err("useful_life_months", "عمر مفید مشخص نیست (نه در ردیف، نه در طبقه)")
        if start and start > lk.run.balance_date and accum > 0:
            chk.err("depreciation_start_date", "استهلاک انباشته دارد ولی شروع استهلاک بعد از برش است")
        elapsed = v["elapsed_months"]
        if elapsed is None and start and method != "NONE":
            elapsed = decimal.Decimal(max(fc.months_between(start, lk.run.balance_date), 0))
        elapsed_int = int(elapsed or 0)
        if life and elapsed_int > life:
            chk.err("elapsed_months", "ماه‌های مستهلک‌شده از عمر مفید بیشتر است")
        if method != "NONE" and accum == 0 and elapsed_int > 0:
            chk.warn("accumulated_depreciation", "ماه‌های مستهلک‌شده دارد ولی استهلاک انباشته صفر است")
        if cost is not None and residual > cost - accum:
            chk.err("residual_value", "ارزش اسقاط از ارزش دفتری بیشتر است")
        location = None
        if v["location_code"]:
            location = lk.s.scalar(select(AssetLocation).where(AssetLocation.company_id == lk.company_id,
                                                               AssetLocation.code == v["location_code"]))
            if location is None:
                chk.err("location_code", f"محل «{v['location_code']}» تعریف نشده است")
        dims: dict[int, int] = {}
        _detail_code(lk, chk, "cost_center_code", "COST_CENTER", v["cost_center_code"], dims)
        _detail_code(lk, chk, "project_code", "PROJECT", v["project_code"], dims)
        if cat is not None and not v["cost_center_code"] and not cat.default_cost_center_detail_account_id and (
                cat.cost_center_required or getattr(lk.s.get(AssetSettings, lk.company_id), "require_cost_center", False)):
            chk.err("cost_center_code", "این طبقه مرکز هزینه را الزامی کرده است")
        branch = lk.branches().get(v["branch_code"]) if v["branch_code"] else None
        if v["branch_code"] and branch is None:
            chk.err("branch_code", f"شعبهٔ «{v['branch_code']}» تعریف نشده است")
        status = v["status"] or "IN_SERVICE"
        if life and elapsed_int >= life and method != "NONE":
            chk.warn("elapsed_months", "دارایی کاملاً مستهلک شده است")
        cc_type, pj_type = lk.dim_types().get("COST_CENTER"), lk.dim_types().get("PROJECT")
        chk.resolved = {"category_id": cat.category_id if cat else None, "asset_account_id": cat.asset_account_id if cat else None,
                        "accum_account_id": cat.accumulated_depreciation_account_id if cat else None,
                        "cost": str(cost or 0), "accumulated": str(accum), "residual": str(residual), "method": method,
                        "life_months": str(life) if life else None, "elapsed_months": elapsed_int, "start": start,
                        "acquisition_date": v["acquisition_date"], "location_id": location.location_id if location else None,
                        "cost_center_id": dims.get(cc_type), "project_id": dims.get(pj_type),
                        "branch_id": branch.branch_id if branch else None, "status": status, "name": v["name"],
                        "serial_no": v["serial_no"] or None}
        chk.amount = c.money((cost or c.ZERO) - accum)
        return chk


class WipHandler(Handler):
    """کالای در جریان ساخت: دستور تازه برای مقدار باقی‌مانده + هزینهٔ انباشتهٔ تأییدشده."""
    code = "WIP"
    columns = [
        Column("legacy_order_no", "شمارهٔ دستور در سیستم قبلی", True),
        Column("item_code", "کد محصول", True),
        Column("remaining_qty", "مقدار باقی‌مانده برای تولید", True, "decimal"),
        Column("wip_amount", "هزینهٔ انباشتهٔ در جریان ساخت", True, "decimal"),
        Column("start_date", "تاریخ شروع", kind="date"),
        Column("due_date", "موعد تحویل", kind="date"),
        Column("material_warehouse_code", "کد انبار مواد"),
        Column("fg_warehouse_code", "کد انبار محصول"),
        Column("cost_center_code", "کد مرکز هزینه"),
        Column("project_code", "کد پروژه"),
        Column("description", "شرح"),
    ]

    def key(self, v: dict, lk: Lookups | None = None) -> str:
        return v["legacy_order_no"]

    def validate(self, lk: Lookups, v: dict) -> Check:
        chk = Check()
        item = lk.items().get(v["item_code"])
        if item is None:
            chk.err("item_code", f"محصول «{v['item_code']}» تعریف نشده است")
        elif not item.is_active:
            chk.err("item_code", "محصول غیرفعال است")
        elif item.has_variants:
            chk.err("item_code", "کالای اصلی متغیردار تولید نمی‌شود؛ کد متغیر را وارد کنید")
        else:
            from peecha.services.production import master as pm

            if pm.effective_bom_id(lk.s, item.item_id, v["start_date"] or lk.run.go_live_date) is None:
                chk.err("item_code", "این محصول فهرست مواد معتبر ندارد؛ دستور تولید بدون فهرست مواد ساخته نمی‌شود")
        if v["remaining_qty"] is not None and v["remaining_qty"] <= 0:
            chk.err("remaining_qty", "مقدار باقی‌مانده باید مثبت باشد؛ دستور تمام‌شده را منتقل نکنید")
        if v["wip_amount"] is not None and v["wip_amount"] < 0:
            chk.err("wip_amount", "هزینهٔ انباشته منفی پذیرفته نمی‌شود")
        if lk.inv_mapping("PRODUCTION_WIP") is None:
            chk.err("wip_amount", "حساب «کالای در جریان ساخت» در تنظیمات انبار نگاشت نشده است")
        whs = {}
        for col in ("material_warehouse_code", "fg_warehouse_code"):
            if v[col]:
                wh = lk.warehouses().get(v[col])
                if wh is None:
                    chk.err(col, f"انبار «{v[col]}» تعریف نشده است")
                whs[col] = wh.warehouse_id if wh else None
        dims: dict[int, int] = {}
        _detail_code(lk, chk, "cost_center_code", "COST_CENTER", v["cost_center_code"], dims)
        _detail_code(lk, chk, "project_code", "PROJECT", v["project_code"], dims)
        cc_type, pj_type = lk.dim_types().get("COST_CENTER"), lk.dim_types().get("PROJECT")
        chk.resolved = {"item_id": item.item_id if item else None, "remaining_qty": str(v["remaining_qty"] or 0),
                        "wip_amount": str(v["wip_amount"] or 0), "start_date": v["start_date"], "due_date": v["due_date"],
                        "material_warehouse_id": whs.get("material_warehouse_code"),
                        "fg_warehouse_id": whs.get("fg_warehouse_code"), "cost_center_id": dims.get(cc_type),
                        "project_id": dims.get(pj_type), "legacy_order_no": v["legacy_order_no"], "description": v["description"]}
        chk.amount = c.money(v["wip_amount"] or 0)
        return chk


HANDLERS: dict[str, Handler] = {
    "GL": GLHandler(), "INVENTORY": InventoryHandler(), "RECEIVABLES": OpenItemsHandler("RECEIVABLES"),
    "PAYABLES": OpenItemsHandler("PAYABLES"), "CHEQUES": ChequesHandler(), "FIXED_ASSETS": FixedAssetsHandler(),
    "WIP": WipHandler(),
}


def handler(module_code: str) -> Handler:
    h = HANDLERS.get(module_code)
    if h is None:
        raise ValueError("ماژول نامعتبر است.")
    return h


def normalize(h: Handler, raw: dict) -> tuple[dict, dict, list[tuple[str, str]]]:
    """(متن تمیز برای ذخیره، مقدار نوع‌دار، خطای قالب). ستون ناشناخته کنار گذاشته می‌شود."""
    payload, values, errors = {}, {}, []
    for col in h.columns:
        cell = raw.get(col.key)
        txt = c.text(cell)
        payload[col.key] = txt if not isinstance(cell, (datetime.date, datetime.datetime)) else c.fmt_date(
            cell.date() if isinstance(cell, datetime.datetime) else cell)
        value = None
        try:
            if col.kind == "decimal":
                value = c.parse_decimal(cell)
            elif col.kind == "date":
                value = c.parse_date(cell)
            elif col.kind == "choice":
                if txt:
                    value = col.choices.get(txt) if txt in col.choices else col.choices.get(txt.lower())
                    if value is None and txt.upper() in set(col.choices.values()):
                        value = txt.upper()
                    if value is None:
                        errors.append((col.key, f"مقدار «{txt}» مجاز نیست ({'، '.join(k for k in col.choices if not k.isascii())})"))
            else:
                value = txt
        except ValueError as exc:
            errors.append((col.key, str(exc)))
        if col.required and (value is None or value == ""):
            if not any(e[0] == col.key for e in errors):
                errors.append((col.key, "الزامی است"))
        values[col.key] = value if value is not None else ("" if col.kind == "text" else None)
    return payload, values, errors
