"""فرم سند افتتاحیه (R315): همهٔ حساب‌های کدینگ با ماندهٔ افتتاحیه، بسته‌شده با حساب افتتاحیه.

با انتخاب هر حساب، ماندهٔ خود حساب، ماندهٔ تفصیلی‌ها، کالاها (مقدار و مبلغ) یا اشخاص (سند باز خودکار) گرفته می‌شود.
این فقط لایهٔ ورود روی همان فرایند افتتاحیه است: ردیف‌ها با importer در ماژول‌های تراز/موجودی/دریافتنی/پرداختنی
ذخیره می‌شوند و ارسال، تأیید، ثبت قطعی، تطبیق، قفل و اصلاح همان سرویس‌های قبلی‌اند. ماندهٔ حساب کنترل زیرسیستم از
جزئیات همان زیرسیستم ساخته و به‌صورت ردیف خودکار تراز نگه داشته می‌شود تا کنترل تراز و تطبیق همان بماند.
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.opening import ImportBatch, OpeningRun, RunModule, StagedRow
from peecha.services.opening import common as c
from peecha.services.opening import importer, reconcile, runs
from peecha.services.opening.modules import Lookups

SHEET_MODULES = ("GL", "INVENTORY", "RECEIVABLES", "PAYABLES")
PARTY_BALANCE_NO = "مانده افتتاحیه"
AUTO_SOURCE = "محاسبهٔ خودکار ماندهٔ حساب‌های کنترل (فرم سند افتتاحیه)"
KIND_LABELS = {
    "GROUP": "", "PLAIN": "مانده", "DETAIL": "مانده به تفکیک تفصیلی", "INVENTORY": "کالاها: مقدار و مبلغ",
    "RECEIVABLES": "مانده هر شخص (سند باز خودکار)", "PAYABLES": "مانده هر شخص (سند باز خودکار)",
    "CHEQUES": "چک‌های باز", "FIXED_ASSETS": "دارایی‌های ثابت", "WIP": "دستورهای تولید باز", "CLEARING": "حساب افتتاحیه (بستن سند)",
}
SUBLEDGER_KINDS = ("INVENTORY", "RECEIVABLES", "PAYABLES", "CHEQUES", "FIXED_ASSETS", "WIP")
_LIVE = ("VALID", "INVALID", "FAILED", "POSTED")
_UNIT_COST = decimal.Decimal("0.0000000001")


def _dec(value) -> decimal.Decimal:
    try:
        return c.parse_decimal(value) or c.ZERO
    except ValueError:
        return c.ZERO


def _plain(value) -> str:
    if value is None or value == "":
        return ""
    text = format(c.dec(value), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


# --- فرایند ------------------------------------------------------------------------------------------------
def default_run(company_id: int) -> int | None:
    """فرایند در جریان (پیش از قفل)؛ وگرنه آخرین فرایند."""
    items = runs.list_runs(company_id, include_cancelled=False)
    live = [r for r in items if r.status_code != "LOCKED"]
    return (live or items)[0].run_id if (live or items) else None


def create_run(company_id: int, user_id: int, fiscal_year_id: int, balance_date: datetime.date,
               go_live_date: datetime.date | None = None, title: str | None = None) -> int:
    """فرایند تازه از فرم سند افتتاحیه با ماژول‌های تراز، موجودی و اشخاص؛ کد از سال مالی ساخته می‌شود."""
    from peecha.db.models.accounting import FiscalYear

    with new_session() as session:
        fy = session.get(FiscalYear, fiscal_year_id)
        fy_code = fy.code if fy is not None and fy.company_id == company_id else str(fiscal_year_id)
        used = set(session.scalars(select(OpeningRun.code).where(OpeningRun.company_id == company_id)))
    code, n = f"OPN-{fy_code}"[:30], 2
    while code in used:
        code, n = f"OPN-{fy_code}-{n}"[:30], n + 1
    return runs.create_run(company_id, user_id, code, (title or f"سند افتتاحیه سال {fy_code}").strip(), fiscal_year_id, balance_date,
                           list(SHEET_MODULES), go_live_date=go_live_date)


# --- نوع ورود هر حساب -------------------------------------------------------------------------------------
def _kinds(session, company_id: int, run_id: int) -> dict[int, str]:
    from peecha.db.models.accounting import AccountDetailDimension, ChartOfAccount

    out: dict[int, str] = dict(reconcile.control_accounts(session, company_id, run_id))
    clearing = c.clearing_account_id(company_id)
    if clearing:
        out[clearing] = "CLEARING"
    for acc in session.scalars(select(AccountDetailDimension.account_id).join(
            ChartOfAccount, ChartOfAccount.account_id == AccountDetailDimension.account_id).where(
            ChartOfAccount.company_id == company_id).distinct()):
        out.setdefault(acc, "DETAIL")
    return out


def _gl_amounts(r: StagedRow) -> tuple[decimal.Decimal, decimal.Decimal]:
    res = r.resolved or {}
    if "base_debit" in res:
        return c.dec(res["base_debit"]), c.dec(res["base_credit"])
    p = r.payload or {}
    return _dec(p.get("debit")), _dec(p.get("credit"))


def _gl_account(lk: Lookups, r: StagedRow) -> int | None:
    acc = (r.resolved or {}).get("account_id")
    if acc:
        return int(acc)
    hit = lk.account((r.payload or {}).get("account_code") or "")
    return hit.account_id if hit is not None else None


def sheet(company_id: int, run_id: int) -> SimpleNamespace:
    """همهٔ حساب‌ها به ترتیب کد با جمع بدهکار/بستانکار ردیف‌های تراز، نوع ورود و تعداد ایراد؛ گروه‌ها جمع زیرمجموعه.
    ماندهٔ حساب افتتاحیه = جمع بدهکار − جمع بستانکار (صفر یعنی سند بسته می‌شود)."""
    from peecha.db.models.accounting import ChartOfAccount
    from peecha.services import chart_of_accounts as coa

    names = {a.account_id: a.name for a in coa.list_accounts(company_id)}
    with new_session() as session:
        run = runs._run(session, company_id, run_id)
        lk = Lookups(session, company_id, run)
        kinds = _kinds(session, company_id, run_id)
        accounts = list(session.scalars(select(ChartOfAccount).where(ChartOfAccount.company_id == company_id)
                                        .order_by(ChartOfAccount.full_code)))
        modules = {m.module_code: m.status_code for m in session.scalars(select(RunModule).where(RunModule.run_id == run_id))}
        sums: dict[int, list] = {}
        for r in session.scalars(select(StagedRow).where(StagedRow.run_id == run_id, StagedRow.module_code == "GL",
                                                         StagedRow.status_code.in_(_LIVE))):
            acc = _gl_account(lk, r)
            if acc is None:
                continue
            d, cr = _gl_amounts(r)
            s = sums.setdefault(acc, [c.ZERO, c.ZERO, 0, 0])
            s[0], s[1], s[2] = s[0] + d, s[1] + cr, s[2] + 1
            s[3] += r.status_code in ("INVALID", "FAILED")
        sub_bad: dict[str, int] = {}
        for r in session.scalars(select(StagedRow).where(StagedRow.run_id == run_id, StagedRow.module_code != "GL",
                                                         StagedRow.status_code.in_(("INVALID", "FAILED")))):
            sub_bad[r.module_code] = sub_bad.get(r.module_code, 0) + 1
        clearing = c.clearing_account_id(company_id)
        parent = {a.account_id: a.parent_account_id for a in accounts}
        status_label = c.RUN_STATUS_LABELS[run.status_code]
        info = SimpleNamespace(run_id=run.run_id, code=run.code, title=run.title, status_code=run.status_code,
                               status_label=status_label, kind_code=run.kind_code, balance_date=run.balance_date,
                               go_live_date=run.go_live_date, editable=run.status_code in runs.ENTRY_RUN)
    totals: dict[int, list] = {}
    debit = credit = c.ZERO
    for acc_id, (d, cr, _n, _bad) in sums.items():
        if acc_id == clearing:
            continue
        debit, credit = debit + d, credit + cr
        node = acc_id
        while node is not None:
            t = totals.setdefault(node, [c.ZERO, c.ZERO])
            t[0], t[1] = t[0] + d, t[1] + cr
            node = parent.get(node)
    difference = c.money(debit - credit)
    rows = []
    for a in accounts:
        d, cr = totals.get(a.account_id, (c.ZERO, c.ZERO))
        if not a.is_active and not (d or cr):
            continue
        kind = kinds.get(a.account_id, "PLAIN") if a.is_postable else "GROUP"
        if kind == "CLEARING":
            d, cr = (c.ZERO, difference) if difference > 0 else (-difference, c.ZERO)
        n, bad = (sums.get(a.account_id) or [0, 0, 0, 0])[2:]
        if kind in SUBLEDGER_KINDS:
            bad += sub_bad.get(kind, 0)
        module = kind if kind in SUBLEDGER_KINDS else "GL"
        rows.append(SimpleNamespace(
            account_id=a.account_id, parent_id=a.parent_account_id, code=a.full_code, name=names.get(a.account_id, ""),
            level=a.account_level, postable=a.is_postable, active=a.is_active, kind=kind, kind_label=KIND_LABELS[kind],
            module=module, module_status=modules.get(module), debit=c.money(d), credit=c.money(cr), lines=n, problems=bad,
            editable=info.editable and a.is_postable and kind != "CLEARING" and modules.get(module) not in runs.LOCKED_MODULE))
    problems = [f"{c.MODULE_LABELS[m]}: {n} ردیف دارای خطا" for m, n in sub_bad.items()]
    if clearing is None:
        problems.insert(0, "«حساب واسط افتتاحیه» (حساب افتتاحیه) در تنظیمات افتتاحیه مشخص نشده است.")
    return SimpleNamespace(run=info, modules=modules, rows=rows, debit=c.money(debit), credit=c.money(credit),
                           difference=difference, closed=difference == 0,
                           clearing=reconcile.account_codes(company_id, [clearing]).get(clearing) if clearing else None,
                           problems=problems)


# --- ردیف خودکار حساب‌های کنترل -------------------------------------------------------------------------------
def _auto_batch(session, run_id: int, user_id: int | None, create: bool) -> int | None:
    batch = session.scalar(select(ImportBatch).where(ImportBatch.run_id == run_id, ImportBatch.module_code == "GL",
                                                     ImportBatch.source_code == "FORM", ImportBatch.file_name == AUTO_SOURCE))
    if batch is None and create:
        version = (session.scalar(select(func.max(ImportBatch.version_no)).where(
            ImportBatch.run_id == run_id, ImportBatch.module_code == "GL")) or 0) + 1
        batch = ImportBatch(run_id=run_id, module_code="GL", version_no=version, source_code="FORM", file_name=AUTO_SOURCE,
                            uploaded_by_user_id=user_id)
        session.add(batch)
        session.flush()
    return batch.batch_id if batch is not None else None


def sync_control_rows(company_id: int, user_id: int, run_id: int) -> int:
    """ماندهٔ تراز حساب‌های کنترل = جمع جزئیات زیرسیستم (دریافتنی/پرداختنی به تفکیک شخص)؛ ردیف خودکار تراز ساخته،
    به‌روز یا حذف می‌شود. حسابی که ردیف تراز واردشده (فایل یا فرم) دارد دست نمی‌خورد تا تطبیق معنا داشته باشد.
    خروجی: تعداد ردیف تغییرکرده."""
    from peecha.db.models.accounting import ChartOfAccount, DetailAccount

    with new_session() as session:
        run = runs._run(session, company_id, run_id)
        gl = session.get(RunModule, (run_id, "GL"))
        if run.status_code not in runs.ENTRY_RUN or gl is None or gl.status_code in runs.LOCKED_MODULE:
            return 0
        ctrl = reconcile.control_accounts(session, company_id, run_id)
        if not ctrl:
            return 0
        lk = Lookups(session, company_id, run)
        expected = {k: v for k, v in reconcile._expected(session, company_id, run_id).items() if k[0] in ctrl and c.money(v)}
        auto_id = _auto_batch(session, run_id, user_id, create=bool(expected))
        manual: set[int] = set()
        current: dict[str, SimpleNamespace] = {}
        for r in session.scalars(select(StagedRow).where(StagedRow.run_id == run_id, StagedRow.module_code == "GL",
                                                         StagedRow.status_code != "REVERSED")):
            acc = _gl_account(lk, r)
            if auto_id is not None and r.batch_id == auto_id:
                current[r.row_key] = SimpleNamespace(row_id=r.row_id, status_code=r.status_code, amount=c.dec(r.amount))
            elif acc in ctrl:
                manual.add(acc)
        codes = {a.account_id: a.full_code for a in session.scalars(select(ChartOfAccount).where(ChartOfAccount.account_id.in_(ctrl)))}
        parties = {k[1] for k in expected if k[1]}
        people = {d.detail_account_id: d.code for d in session.scalars(
            select(DetailAccount).where(DetailAccount.detail_account_id.in_(parties or [-1])))}
        if auto_id is not None:
            session.commit()
    items, keep = [], set()
    for (acc, party), amount in sorted(expected.items(), key=lambda kv: (codes.get(kv[0][0], ""), people.get(kv[0][1], ""))):
        if acc in manual:
            continue
        amount = c.money(amount)
        person = people.get(party, "") if party else ""
        key = "|".join([codes[acc], person, "", "", "", ""])
        keep.add(key)
        row = current.get(key)
        if row is not None and row.status_code != "INVALID" and row.amount == amount:
            continue
        items.append((row.row_id if row is not None else None, {
            "account_code": codes[acc], "debit": str(amount) if amount > 0 else "", "credit": str(-amount) if amount < 0 else "",
            "person_code": person, "description": f"از {c.MODULE_LABELS[ctrl[acc]]}"}))
    drop = [r.row_id for k, r in current.items() if k not in keep and r.status_code != "POSTED"]
    if not items and not drop:
        return 0
    res = importer.save_rows(company_id, user_id, run_id, "GL", items, drop, batch_id=auto_id)
    return len(res.saved) + res.deleted


# --- حساب ساده یا تفصیلی ------------------------------------------------------------------------------------
_DIM_FIELD = {"PERSON": "person_code", "COST_CENTER": "cost_center_code", "PROJECT": "project_code"}


def _dims(session, lk: Lookups, account_id: int) -> list[SimpleNamespace]:
    from peecha.db.models.accounting import AccountDetailDimension

    codes = {v: k for k, v in lk.dim_types().items()}
    out = []
    for d in session.scalars(select(AccountDetailDimension).where(AccountDetailDimension.account_id == account_id)):
        code = codes.get(d.dimension_type_id, "")
        out.append(SimpleNamespace(type_id=d.dimension_type_id, code=code, label=lk.dim_label(d.dimension_type_id),
                                   field=_DIM_FIELD.get(code, f"other:{code}"), required=bool(d.is_required)))
    return sorted(out, key=lambda x: (x.code != "PERSON", x.type_id))


def _details_from_payload(payload: dict) -> dict[str, str]:
    out = {k: payload.get(k) or "" for k in _DIM_FIELD.values() if payload.get(k)}
    for part in (payload.get("other_details") or "").replace("،", ",").split(","):
        if ":" in part:
            dim, code = (x.strip() for x in part.split(":", 1))
            out[f"other:{dim.upper()}"] = code
    return out


def _row_text(r: StagedRow) -> str:
    return "؛ ".join(f"{e['label']}: {e['msg']}" for e in (r.errors or []))


def account_detail(company_id: int, run_id: int, account_id: int) -> SimpleNamespace:
    """ردیف‌های تراز یک حساب و فهرست تفصیلی‌های اصلی آن (مثلاً همهٔ اشخاص مجاز) برای ورود مانده."""
    from peecha.db.models.accounting import ChartOfAccount, DetailAccount

    with new_session() as session:
        run = runs._run(session, company_id, run_id)
        lk = Lookups(session, company_id, run)
        acc = session.get(ChartOfAccount, account_id)
        if acc is None or acc.company_id != company_id:
            raise ValueError("حساب نامعتبر است.")
        dims = _dims(session, lk, account_id)
        lines = []
        for r in session.scalars(select(StagedRow).where(StagedRow.run_id == run_id, StagedRow.module_code == "GL",
                                                         StagedRow.status_code.in_(_LIVE)).order_by(StagedRow.row_id)):
            if _gl_account(lk, r) != account_id:
                continue
            p = r.payload or {}
            lines.append(SimpleNamespace(row_id=r.row_id, details=_details_from_payload(p), debit=_dec(p.get("debit")),
                                         credit=_dec(p.get("credit")), currency_code=p.get("currency_code") or "",
                                         exchange_rate=p.get("exchange_rate") or "", description=p.get("description") or "",
                                         status=r.status_code, problem=_row_text(r), posted=r.status_code == "POSTED"))
        candidates = []
        primary = dims[0] if dims else None
        if primary is not None:
            q = select(DetailAccount).where(DetailAccount.company_id == company_id,
                                            DetailAccount.dimension_type_id == primary.type_id, DetailAccount.is_active.is_(True))
            groups = lk.person_groups(account_id) if primary.code == "PERSON" else set()
            if groups:
                q = q.where(DetailAccount.person_group_id.in_(groups))
            candidates = [(d.code, d.name or "") for d in session.scalars(q.order_by(DetailAccount.code))]
    label = reconcile.account_codes(company_id, [account_id]).get(account_id, acc.full_code)
    return SimpleNamespace(account_id=account_id, code=acc.full_code, label=label, dims=dims, primary=primary,
                           candidates=candidates, lines=lines)


def _gl_values(code: str, line: dict) -> dict:
    details = line.get("details") or {}
    other = ",".join(f"{k.split(':', 1)[1]}:{v}" for k, v in sorted(details.items()) if k.startswith("other:") and v)
    return {"account_code": code, "debit": _plain(line.get("debit")) if line.get("debit") else "",
            "credit": _plain(line.get("credit")) if line.get("credit") else "",
            "person_code": details.get("person_code", ""), "cost_center_code": details.get("cost_center_code", ""),
            "project_code": details.get("project_code", ""), "other_details": other,
            "currency_code": line.get("currency_code") or "", "exchange_rate": line.get("exchange_rate") or "",
            "description": line.get("description") or ""}


def save_account_detail(company_id: int, user_id: int, run_id: int, account_id: int, lines: list[dict]) -> SimpleNamespace:
    """ردیف‌های مانده یک حساب: ردیف با مبلغ ذخیره، ردیف موجود بی‌مبلغ حذف می‌شود. lines: row_id، details
    ({person_code، cost_center_code، project_code، other:کد}: کد تفصیلی)، debit، credit، currency_code، exchange_rate، description."""
    from peecha.db.models.accounting import ChartOfAccount

    with new_session() as session:
        acc = session.get(ChartOfAccount, account_id)
        if acc is None or acc.company_id != company_id:
            raise ValueError("حساب نامعتبر است.")
        if acc.account_id == c.clearing_account_id(company_id):
            raise ValueError("حساب افتتاحیه خودکار بسته می‌شود و مانده نمی‌گیرد.")
        if reconcile.control_accounts(session, company_id, run_id).get(account_id):
            raise ValueError("ماندهٔ این حساب از جزئیات زیرسیستم ساخته می‌شود.")
        code = acc.full_code
    items, drop = [], []
    for line in lines:
        debit, credit = c.dec(line.get("debit")), c.dec(line.get("credit"))
        if debit or credit:
            items.append((line.get("row_id"), _gl_values(code, {**line, "debit": debit, "credit": credit})))
        elif line.get("row_id"):
            drop.append(line["row_id"])
    return importer.save_rows(company_id, user_id, run_id, "GL", items, drop)


# --- کالاها ------------------------------------------------------------------------------------------------
_INV_EXTRA = ("uom_code", "bin_code", "batch_no", "serial_no", "expiry_date", "manufacture_date", "quality_status", "currency_code",
              "exchange_rate", "description")


def warehouses(company_id: int) -> list[SimpleNamespace]:
    from peecha.db.models.inventory import Warehouse

    with new_session() as session:
        return [SimpleNamespace(warehouse_id=w.warehouse_id, code=w.code, name=w.name) for w in session.scalars(
            select(Warehouse).where(Warehouse.company_id == company_id, Warehouse.is_active.is_(True)).order_by(Warehouse.code))]


def inventory_detail(company_id: int, run_id: int, warehouse_code: str) -> SimpleNamespace:
    """همهٔ کالاهای موجودی‌دار با ردیف‌های موجودی همین انبار (هر بچ/سریال/محل یک ردیف)؛ کالای بی‌ردیف با مقدار خالی."""
    from peecha.services import inventory_catalog

    items = [i for i in inventory_catalog.list_items(company_id, active_only=True, transactable_only=True)
             if i.is_stock_tracked and i.item_kind_code != "SERVICE"]
    by_code = {i.code: i for i in items}
    with new_session() as session:
        runs._run(session, company_id, run_id)
        rows = [r for r in session.scalars(select(StagedRow).where(
            StagedRow.run_id == run_id, StagedRow.module_code == "INVENTORY", StagedRow.status_code.in_(_LIVE))
            .order_by(StagedRow.row_id)) if (r.payload or {}).get("warehouse_code") == warehouse_code]
        lines, seen = [], set()
        for r in rows:
            p = dict(r.payload or {})
            item = by_code.get(p.get("item_code"))
            qty, unit = _dec(p.get("quantity")), _dec(p.get("unit_cost"))
            seen.add(p.get("item_code"))
            lines.append(SimpleNamespace(row_id=r.row_id, item_code=p.get("item_code") or "", item_name=item.name if item else "",
                                         base_uom=item.base_uom_code if item else "", quantity=qty, amount=c.money(qty * unit),
                                         payload=p, status=r.status_code, problem=_row_text(r), posted=r.status_code == "POSTED",
                                         tracked=bool(item and (item.track_batch or item.track_serial or item.track_expiry))))
    for i in items:
        if i.code not in seen:
            lines.append(SimpleNamespace(row_id=None, item_code=i.code, item_name=i.name or "", base_uom=i.base_uom_code,
                                         quantity=None, amount=None, payload={}, status=None, problem="", posted=False,
                                         tracked=i.track_batch or i.track_serial or i.track_expiry))
    lines.sort(key=lambda x: (x.item_code, x.row_id is None, x.row_id or 0))
    return SimpleNamespace(warehouse_code=warehouse_code, lines=lines)


def save_inventory(company_id: int, user_id: int, run_id: int, warehouse_code: str, lines: list[dict]) -> SimpleNamespace:
    """هر ردیف: کالا، مقدار و مبلغ کل (بهای واحد = مبلغ ÷ مقدار) با فیلدهای ردیابی؛ ردیف موجود بی‌مقدار حذف می‌شود."""
    items, drop = [], []
    for line in lines:
        qty, amount = c.dec(line.get("quantity")), line.get("amount")
        if qty:
            unit = (c.dec(amount) / qty).quantize(_UNIT_COST) if amount not in (None, "") else None
            extra = {k: line.get(k) or "" for k in _INV_EXTRA}
            items.append((line.get("row_id"), {**extra, "warehouse_code": warehouse_code, "item_code": line.get("item_code") or "",
                                               "quantity": _plain(qty), "unit_cost": _plain(unit) if unit is not None else ""}))
        elif line.get("row_id"):
            drop.append(line["row_id"])
    return importer.save_rows(company_id, user_id, run_id, "INVENTORY", items, drop)


# --- اشخاص (دریافتنی/پرداختنی) -----------------------------------------------------------------------------
def party_detail(company_id: int, run_id: int, module_code: str) -> SimpleNamespace:
    """اشخاص مجاز حساب کنترل با ماندهٔ افتتاحیهٔ هر شخص (یک سند باز خودکار یا پیش‌دریافت/پیش‌پرداخت) و جمع سایر
    اسناد باز همان شخص (از فایل یا مرکز افتتاحیه)."""
    from peecha.db.models.accounting import DetailAccount, PersonGroup

    if module_code not in ("RECEIVABLES", "PAYABLES"):
        raise ValueError("ماژول نامعتبر است.")
    receivable = module_code == "RECEIVABLES"
    with new_session() as session:
        run = runs._run(session, company_id, run_id)
        lk = Lookups(session, company_id, run)
        person_type = lk.dim_types().get("PERSON")
        ctrl = lk.inv_mapping("CUSTOMER_RECEIVABLE" if receivable else "SUPPLIER_PAYABLE")
        q = select(DetailAccount).where(DetailAccount.company_id == company_id, DetailAccount.dimension_type_id == person_type,
                                        DetailAccount.is_active.is_(True))
        groups = lk.person_groups(ctrl) if ctrl else set()
        if not groups:
            # بدون محدودیت گروه روی حساب: مشتریان برای دریافتنی، تامین‌کنندگان برای پرداختنی
            group = session.scalar(select(PersonGroup.person_group_id).where(
                PersonGroup.company_id == company_id, PersonGroup.code == ("CUSTOMER" if receivable else "SUPPLIER")))
            groups = {group} if group is not None else set()
        if groups:
            q = q.where(DetailAccount.person_group_id.in_(groups))
        people = [(d.code, d.name or "") for d in session.scalars(q.order_by(DetailAccount.code))]
        summary: dict[str, StagedRow] = {}
        other: dict[str, list] = {}
        for r in session.scalars(select(StagedRow).where(StagedRow.run_id == run_id, StagedRow.module_code == module_code,
                                                         StagedRow.status_code.in_(_LIVE)).order_by(StagedRow.row_id)):
            p = r.payload or {}
            code = p.get("counterparty_code") or ""
            if p.get("legacy_no") == PARTY_BALANCE_NO:
                summary[code] = r
            else:
                o = other.setdefault(code, [c.ZERO, 0])
                o[0], o[1] = o[0] + c.dec(r.amount), o[1] + 1
        known = {code for code, _n in people}
        people += [(code, "") for code in sorted(set(summary) | set(other)) if code not in known]
        lines = []
        for code, name in people:
            r = summary.get(code)
            debit = credit = c.ZERO
            due = ""
            if r is not None:
                p = r.payload or {}
                amount = _dec(p.get("original_amount"))
                advance = (r.resolved or {}).get("advance") or p.get("balance_kind") in ("پیش‌دریافت", "پیش‌پرداخت", "ADVANCE")
                if receivable != bool(advance):
                    debit = amount
                else:
                    credit = amount
                due = p.get("due_date") or ""
            o = other.get(code, [c.ZERO, 0])
            signed = o[0] if receivable else -o[0]
            lines.append(SimpleNamespace(person_code=code, name=name, row_id=r.row_id if r is not None else None, debit=debit,
                                         credit=credit, due_date=due, other_amount=c.money(signed), other_count=o[1],
                                         status=r.status_code if r is not None else None, problem=_row_text(r) if r is not None else "",
                                         posted=bool(r is not None and r.status_code == "POSTED")))
    return SimpleNamespace(module_code=module_code, receivable=receivable, lines=lines)


def save_parties(company_id: int, user_id: int, run_id: int, module_code: str, lines: list[dict]) -> SimpleNamespace:
    """ماندهٔ هر شخص: ماندهٔ هم‌جهت حساب ← یک سند باز افتتاحیه (تا در تسویه و گزارش سنی دیده شود)، خلاف جهت ←
    پیش‌دریافت/پیش‌پرداخت. بدهکار و بستانکار هم‌زمان خالص می‌شوند."""
    receivable = module_code == "RECEIVABLES"
    with new_session() as session:
        balance_date = runs._run(session, company_id, run_id).balance_date
    items, drop = [], []
    for line in lines:
        net = c.dec(line.get("debit")) - c.dec(line.get("credit"))
        if not net:
            if line.get("row_id"):
                drop.append(line["row_id"])
            continue
        open_item = (net > 0) == receivable
        due = line.get("due_date")
        items.append((line.get("row_id"), {
            "counterparty_code": line.get("person_code") or "", "legacy_no": PARTY_BALANCE_NO, "legacy_type": "مانده حساب",
            "doc_date": balance_date, "due_date": (due or "") if open_item else "", "original_amount": _plain(abs(net)),
            "balance_kind": "سند باز" if open_item else ("پیش‌دریافت" if receivable else "پیش‌پرداخت"), "description": ""}))
    return importer.save_rows(company_id, user_id, run_id, module_code, items, drop)


# --- گردش کار از همین فرم ------------------------------------------------------------------------------------
def _each(company_id: int, user_id: int, run_id: int, statuses: tuple, fn, *extra) -> SimpleNamespace:
    run = runs.get_run(company_id, run_id)
    done, problems = [], []
    for m in run.modules:
        if m.status_code == "HAS_ERRORS" and "ENTERING" in statuses:
            problems.append(f"{m.label}: ردیف دارای خطا دارد")
            continue
        if m.status_code not in statuses:
            continue
        try:
            fn(company_id, user_id, run_id, m.module_code, *extra)
            done.append(m.label)
        except ValueError as exc:
            problems.append(f"{m.label}: {exc}")
    if not done and problems:
        raise ValueError("\n".join(problems))
    return SimpleNamespace(done=done, problems=problems)


def submit_all(company_id: int, user_id: int, run_id: int, comment: str | None = None) -> SimpleNamespace:
    """ارسال همهٔ ماژول‌های واردشده و بی‌خطا برای بررسی."""
    if c.can(company_id, user_id, c.FORM_ENTER):
        sync_control_rows(company_id, user_id, run_id)
    res = _each(company_id, user_id, run_id, ("ENTERING",), runs.submit, comment)
    if not res.done and not res.problems:
        raise ValueError("ماژولی برای ارسال نیست؛ ابتدا مانده‌ها را وارد کنید.")
    return res


def approve_all(company_id: int, user_id: int, run_id: int, comment: str | None = None) -> SimpleNamespace:
    res = _each(company_id, user_id, run_id, ("READY",), runs.approve, comment)
    if not res.done and not res.problems:
        raise ValueError("ماژولی منتظر تأیید نیست.")
    return res


def reject_all(company_id: int, user_id: int, run_id: int, reason: str) -> SimpleNamespace:
    if not (reason or "").strip():
        raise ValueError("دلیل رد را بنویسید.")
    res = _each(company_id, user_id, run_id, ("READY", "APPROVED"), runs.reject, reason)
    if not res.done and not res.problems:
        raise ValueError("ماژولی برای رد نیست.")
    return res


def post_all(company_id: int, user_id: int, run_id: int, difference_reason: str | None = None) -> SimpleNamespace:
    """ثبت قطعی همهٔ ماژول‌های تأییدشده به ترتیب رسمی (زیرسیستم‌ها، سپس سند تراز با حساب افتتاحیه)."""
    from peecha.services.opening import posting

    run = runs.get_run(company_id, run_id)
    status = {m.module_code: m for m in run.modules}
    waiting = [m.label for m in run.modules if m.status_code in ("ENTERING", "HAS_ERRORS", "READY")]
    if waiting:
        raise ValueError("ابتدا این بخش‌ها ارسال و تأیید شوند: " + "، ".join(waiting))
    gl = status.get("GL")
    if gl is not None and gl.status_code not in ("POSTED", "LOCKED"):
        # پیش از ثبت هر بخش: سند باید با حساب افتتاحیه صفر بسته شود تا زیرسیستمی نیمه‌کاره ثبت نشود
        rec = reconcile.report(company_id, run_id)
        if not rec.tb_balanced:
            raise ValueError(f"سند افتتاحیه بسته نمی‌شود: جمع بدهکار {rec.tb_debit:,} و جمع بستانکار {rec.tb_credit:,} است؛ "
                             f"ماندهٔ حساب افتتاحیه ({rec.tb_debit - rec.tb_credit:,}) باید صفر شود.")
        if rec.projected_clearing and c.settings(company_id).difference_policy != "APPROVAL":
            raise ValueError(f"جزئیات زیرسیستم‌ها با ماندهٔ حساب‌های کنترل {rec.projected_clearing:,} اختلاف دارد؛ "
                             "صفحهٔ تطبیق را ببینید.")
    posted, failed = [], []
    for code in c.POST_ORDER:
        m = status.get(code)
        if m is None or m.status_code not in ("APPROVED", "POSTING"):
            continue
        res = posting.post_module(company_id, user_id, run_id, code, difference_reason if code == "GL" else None)
        if res.failed:
            failed += [f"{m.label}: {msg}" for msg in res.failed]
            break
        posted.append(m.label)
    if not posted and not failed:
        raise ValueError("بخشی برای ثبت قطعی نیست.")
    return SimpleNamespace(posted=posted, failed=failed, run_status=runs.get_run(company_id, run_id).status_code)
