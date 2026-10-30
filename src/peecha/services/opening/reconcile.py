"""تطبیق افتتاحیه (R314): حساب‌های کنترل هر زیرسیستم و مقایسهٔ تراز با جزئیات زیرسیستم.

فرمول: برای هر حساب کنترل a ← اختلاف(a) = ماندهٔ تراز(a) − جمع جزئیات زیرسیستم(a)
(دریافتنی/پرداختنی به تفکیک طرف‌حساب). ماندهٔ حساب واسط پس از ثبت همهٔ ماژول‌ها باید صفر باشد.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.models.opening import RunModule

# نقش نگاشت انبار/خزانه ← ماژول
_INV_ROLES = {"INVENTORY": "INVENTORY_ASSET", "RECEIVABLES": "CUSTOMER_RECEIVABLE", "PAYABLES": "SUPPLIER_PAYABLE",
              "WIP": "PRODUCTION_WIP"}
_TREASURY_ROLES = {"RECEIPT_CHECK": "CHEQUES", "PAYMENT_CHECK": "CHEQUES"}


def control_accounts(session, company_id: int, run_id: int) -> dict[int, str]:
    """حساب ← ماژولی از همین فرایند که ماندهٔ آن را از جزئیات می‌سازد."""
    from peecha.db.models.fixed_assets import AssetCategory
    from peecha.db.models.inventory import InventoryAccountMapping, Warehouse, WarehouseAccountMapping
    from peecha.db.models.treasury import TreasuryAccountMapping

    modules = set(session.scalars(select(RunModule.module_code).where(RunModule.run_id == run_id)))
    out: dict[int, str] = {}
    for module, role in _INV_ROLES.items():
        if module not in modules:
            continue
        row = session.get(InventoryAccountMapping, (company_id, role))
        if row is not None:
            out.setdefault(row.account_id, module)
        if module == "INVENTORY":
            for acc in session.scalars(select(WarehouseAccountMapping.account_id).join(
                    Warehouse, Warehouse.warehouse_id == WarehouseAccountMapping.warehouse_id).where(
                    Warehouse.company_id == company_id, WarehouseAccountMapping.mapping_key == role)):
                out.setdefault(acc, module)
    if "CHEQUES" in modules:
        for acc in session.scalars(select(TreasuryAccountMapping.account_id).where(
                TreasuryAccountMapping.company_id == company_id, TreasuryAccountMapping.mapping_key.in_(_TREASURY_ROLES))):
            out.setdefault(acc, "CHEQUES")
    if "FIXED_ASSETS" in modules:
        for cat in session.scalars(select(AssetCategory).where(AssetCategory.company_id == company_id)):
            for acc in (cat.asset_account_id, cat.accumulated_depreciation_account_id):
                if acc:
                    out.setdefault(acc, "FIXED_ASSETS")
    return out


_PER_PARTY = ("RECEIVABLES", "PAYABLES")
_SOURCES = {"INVENTORY": "ردیف‌های موجودی (مقدار × بهای واحد)", "RECEIVABLES": "اسناد باز دریافتنی (اصلی − تسویه‌شده)",
            "PAYABLES": "اسناد باز پرداختنی (اصلی − تسویه‌شده)", "CHEQUES": "چک‌های باز (دریافتی + / پرداختی −)",
            "FIXED_ASSETS": "دارایی‌ها (بها + / استهلاک انباشته −)", "WIP": "هزینهٔ انباشتهٔ دستورهای باز"}
_FIX = {"INVENTORY": "مقدار یا بهای واحد ردیف‌های موجودی، یا ماندهٔ حساب موجودی در تراز را بررسی کنید",
        "RECEIVABLES": "اسناد باز همین طرف‌حساب یا ماندهٔ او در تراز را بررسی کنید",
        "PAYABLES": "اسناد باز همین طرف‌حساب یا ماندهٔ او در تراز را بررسی کنید",
        "CHEQUES": "فهرست چک‌های باز یا ماندهٔ حساب اسناد دریافتنی/پرداختنی در تراز را بررسی کنید",
        "FIXED_ASSETS": "بها و استهلاک انباشتهٔ دارایی‌ها یا ماندهٔ حساب‌های دارایی در تراز را بررسی کنید",
        "WIP": "هزینهٔ انباشتهٔ دستورها یا ماندهٔ حساب کالای در جریان ساخت را بررسی کنید"}


def account_codes(company_id: int, account_ids) -> dict[int, str]:
    from peecha.services import chart_of_accounts as coa

    ids = {a for a in account_ids if a}
    if not ids:
        return {}
    return {a.account_id: f"{a.full_code} — {a.name}" for a in coa.list_accounts(company_id) if a.account_id in ids}


def _expected(session, company_id: int, run_id: int) -> dict[tuple, Decimal]:
    """اثر مورد انتظار زیرسیستم‌ها بر حساب‌های کنترل، از ردیف‌های معتبر/ثبت‌شده: (حساب، طرف‌حساب) ← مبلغ (بدهکار +)."""
    from peecha.db.models.inventory import InventoryAccountMapping
    from peecha.db.models.opening import StagedRow

    out: dict[tuple, Decimal] = {}

    def add(acc, party, amount):
        if acc:
            out[(int(acc), party)] = out.get((int(acc), party), Decimal(0)) + Decimal(str(amount))

    def mapping(key):
        row = session.get(InventoryAccountMapping, (company_id, key))
        return row.account_id if row else None
    inv_acc, wip_acc = mapping("INVENTORY_ASSET"), mapping("PRODUCTION_WIP")
    for r in session.scalars(select(StagedRow).where(StagedRow.run_id == run_id, StagedRow.module_code != "GL",
                                                     StagedRow.status_code.in_(("VALID", "FAILED", "POSTED")))):
        res = r.resolved or {}
        m = r.module_code
        if m == "INVENTORY":
            add(inv_acc, None, r.amount)
        elif m == "RECEIVABLES":
            add(res.get("account_id"), res.get("counterparty_id"), r.amount)
        elif m == "PAYABLES":
            add(res.get("account_id"), res.get("counterparty_id"), -r.amount)
        elif m == "CHEQUES":
            add(res.get("account_id"), None, r.amount if res.get("kind") == "RECEIVED" else -r.amount)
        elif m == "FIXED_ASSETS":
            add(res.get("asset_account_id"), None, res.get("cost") or 0)
            add(res.get("accum_account_id"), None, -Decimal(str(res.get("accumulated") or 0)))
        elif m == "WIP":
            add(wip_acc, None, r.amount)
    return out


def _posted(session, company_id: int, run_id: int, accounts: set[int], modules: set[str],
            reversals: bool = True) -> dict[tuple, Decimal]:
    """اثر واقعی اسناد ثبت‌شدهٔ همین فرایند بر حساب‌های کنترل (به تفکیک شخص برای دریافتنی/پرداختنی)؛ گام‌های
    ماژول‌های ثبت‌شده و برگشت‌های اصلاحیه."""
    from peecha.db.models.accounting import JournalEntryLine, JournalEntryLineDetail
    from peecha.db.models.opening import Posting
    from peecha.services import detail_dimensions as dims

    q = select(Posting.journal_entry_id).where(Posting.run_id == run_id, Posting.status_code == "DONE",
                                               Posting.journal_entry_id.is_not(None), Posting.module_code != "GL")
    cond = Posting.module_code.in_(modules or ["-"])
    if reversals:
        cond = cond | Posting.step_key.like("REV:%")
    je_ids = set(session.scalars(q.where(cond)))
    if not je_ids or not accounts:
        return {}
    person_type = dims.get_person_dimension_type_id(company_id)
    person = (select(JournalEntryLineDetail.detail_account_id).where(
        JournalEntryLineDetail.line_id == JournalEntryLine.line_id,
        JournalEntryLineDetail.dimension_type_id == person_type).scalar_subquery())
    out: dict[tuple, Decimal] = {}
    for acc, party, dr, cr in session.execute(select(JournalEntryLine.account_id, person, JournalEntryLine.debit_amount_base,
                                                     JournalEntryLine.credit_amount_base).where(
            JournalEntryLine.journal_entry_id.in_(je_ids), JournalEntryLine.account_id.in_(accounts))):
        out[(acc, party)] = out.get((acc, party), Decimal(0)) + Decimal(dr or 0) - Decimal(cr or 0)
    return out


def compute(session, company_id: int, run_id: int) -> SimpleNamespace:
    """گزارش تطبیق: برای هر حساب کنترل (دریافتنی/پرداختنی به تفکیک طرف‌حساب) ماندهٔ تراز، جمع زیرسیستم و اختلاف."""
    from peecha.db.models.accounting import DetailAccount, JournalEntryLine
    from peecha.db.models.opening import OpeningRun, Posting, StagedRow
    from peecha.services.opening import common as c

    run = session.get(OpeningRun, run_id)
    ctrl = control_accounts(session, company_id, run_id)
    statuses = {m.module_code: m.status_code for m in session.scalars(select(RunModule).where(RunModule.run_id == run_id))}
    party_accounts = {a for a, m in ctrl.items() if m in _PER_PARTY}
    from peecha.services import detail_dimensions as dims

    person_dim = str(dims.get_person_dimension_type_id(company_id))
    tb: dict[tuple, Decimal] = {}
    tb_debit = tb_credit = Decimal(0)
    for r in session.scalars(select(StagedRow).where(StagedRow.run_id == run_id, StagedRow.module_code == "GL",
                                                     StagedRow.status_code.in_(("VALID", "FAILED", "POSTED")))):
        res = r.resolved or {}
        tb_debit += Decimal(str(res.get("base_debit") or 0))
        tb_credit += Decimal(str(res.get("base_credit") or 0))
        acc = res.get("account_id")
        if acc in ctrl:
            party = (res.get("details") or {}).get(person_dim) if acc in party_accounts else None
            tb[(acc, party)] = tb.get((acc, party), Decimal(0)) + Decimal(r.amount)
    expected = {k: v for k, v in _expected(session, company_id, run_id).items() if k[0] in ctrl}
    posted_modules = {m for m, s in statuses.items() if s in ("POSTED", "LOCKED")}
    posted = _posted(session, company_id, run_id, set(ctrl), posted_modules)
    sub: dict[tuple, Decimal] = {}
    for key, amount in expected.items():
        if ctrl[key[0]] not in posted_modules:
            sub[key] = amount
    for key, amount in posted.items():
        if key[0] in party_accounts or key[1] is None:
            sub[key] = sub.get(key, Decimal(0)) + amount
        else:
            sub[(key[0], None)] = sub.get((key[0], None), Decimal(0)) + amount
    names = account_codes(company_id, {k[0] for k in set(tb) | set(sub)})
    parties = {k[1] for k in set(tb) | set(sub) if k[1]}
    pnames = {d.detail_account_id: f"{d.code} — {d.name or ''}" for d in session.scalars(
        select(DetailAccount).where(DetailAccount.detail_account_id.in_(parties or [-1])))}
    rows = []
    for key in sorted(set(tb) | set(sub), key=lambda k: (names.get(k[0], ""), pnames.get(k[1], ""))):
        acc, party = key
        module = ctrl[acc]
        t, s = c.money(tb.get(key, 0)), c.money(sub.get(key, 0))
        rows.append(SimpleNamespace(
            module_code=module, module=c.MODULE_LABELS[module], account_id=acc, account=names.get(acc, str(acc)),
            counterparty_id=party, counterparty=pnames.get(party, "") if party else "", tb=t, sub=s, difference=t - s,
            source=_SOURCES[module] + (" — ثبت‌شده" if module in posted_modules else " — پیش از ثبت"),
            formula="اختلاف = ماندهٔ تراز − جمع زیرسیستم", fix=_FIX[module] if t != s else ""))
    clearing = c.clearing_account_id(company_id)
    clearing_posted = Decimal(0)
    if clearing:
        je_ids = set(session.scalars(select(Posting.journal_entry_id).where(
            Posting.run_id == run_id, Posting.status_code == "DONE", Posting.journal_entry_id.is_not(None))))
        if je_ids:
            dr, cr = session.execute(select(func.coalesce(func.sum(JournalEntryLine.debit_amount_base), 0),
                                            func.coalesce(func.sum(JournalEntryLine.credit_amount_base), 0)).where(
                JournalEntryLine.journal_entry_id.in_(je_ids), JournalEntryLine.account_id == clearing)).one()
            clearing_posted = Decimal(dr) - Decimal(cr)
    total_diff = sum((x.difference for x in rows), Decimal(0))
    gl_posted = statuses.get("GL") in ("POSTED", "LOCKED")
    problems = []
    if tb_debit != tb_credit:
        problems.append(f"تراز افتتاحیه تراز نیست (بدهکار {tb_debit:,}، بستانکار {tb_credit:,})")
    for x in rows:
        if x.difference:
            problems.append(f"{x.module}: {x.account} {x.counterparty} اختلاف {x.difference:,}")
    if gl_posted and clearing_posted:
        problems.append(f"ماندهٔ حساب واسط افتتاحیه صفر نیست: {clearing_posted:,}")
    return SimpleNamespace(run_id=run_id, rows=rows, tb_debit=c.money(tb_debit), tb_credit=c.money(tb_credit),
                           tb_balanced=tb_debit == tb_credit, total_difference=c.money(total_diff),
                           projected_clearing=c.money(total_diff), clearing_posted=c.money(clearing_posted),
                           gl_posted=gl_posted, problems=problems,
                           ok=not problems and (not gl_posted or clearing_posted == 0), balance_date=run.balance_date)


def report(company_id: int, run_id: int) -> SimpleNamespace:
    from peecha.db.base import new_session
    from peecha.services.opening import runs

    with new_session() as session:
        runs._run(session, company_id, run_id)
        return compute(session, company_id, run_id)
