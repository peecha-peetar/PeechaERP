"""ثبت قطعی افتتاحیه (R314) — فقط با سرویس رسمی هر ماژول.

هر ماژول به چند «گام» تقسیم می‌شود (کلید یکتا در opn.postings). گامی که DONE شده دوباره اجرا نمی‌شود، پس اجرای دوباره
پس از خطا یا قطع برنامه ادامهٔ همان کار است، نه تکرار آن. گام‌های درون‌تراکنشی (انبار، سند باز، دارایی، دفتر کل)
سند ماژول + ردیف‌ها + وضعیت گام را با هم commit می‌کنند. گام چک که سرویس خزانه خودش commit می‌کند، با نشانهٔ
alternative_number سند بازیابی می‌شود. قفل مشورتی پایگاه داده اجرای هم‌زمان یک ماژول را مانع می‌شود.

طرف مقابل همهٔ ثبت‌ها «حساب واسط افتتاحیه» است؛ سند تراز (دفتر کل) آخر از همه ثبت می‌شود و سهم حساب‌های کنترل را
به حساب واسط می‌برد، پس هر مانده فقط یک بار در دفتر کل می‌نشیند.
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import func, select, text

from peecha.db.base import get_engine, new_session
from peecha.db.models.opening import OpeningRun, Posting, RunModule, StagedRow
from peecha.services.opening import common as c
from peecha.services.opening import reconcile, runs

CHUNK = 200
_LOCK_NS = 314
_DONE_MODULE = ("POSTED", "LOCKED")


def _d(value) -> decimal.Decimal:
    return c.dec(value)


def _date(value) -> datetime.date | None:
    if not value:
        return None
    return value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value)[:10])


# --- قفل و گام ---------------------------------------------------------------------------------------------
class _ModuleLock:
    """قفل مشورتی سطح اتصال برای کل مدت ثبت یک ماژول (گام‌ها تراکنش‌های جدا هستند)."""

    def __init__(self, run_id: int, module_code: str) -> None:
        self.key = run_id * 16 + c.POST_ORDER.index(module_code)
        self.conn = None

    def __enter__(self):
        self.conn = get_engine().connect()
        got = self.conn.execute(text("SELECT pg_try_advisory_lock(:ns, :k)"), {"ns": _LOCK_NS, "k": self.key}).scalar()
        self.conn.commit()
        if not got:
            self.conn.close()
            raise ValueError("ثبت قطعی همین ماژول هم‌اکنون توسط کاربر دیگری در جریان است.")
        return self

    def __exit__(self, *exc):
        try:
            self.conn.execute(text("SELECT pg_advisory_unlock(:ns, :k)"), {"ns": _LOCK_NS, "k": self.key})
            self.conn.commit()
        finally:
            self.conn.close()


def _rows(session, run_id: int, module_code: str, statuses=("VALID", "FAILED")) -> list[StagedRow]:
    return list(session.scalars(select(StagedRow).where(
        StagedRow.run_id == run_id, StagedRow.module_code == module_code, StagedRow.status_code.in_(statuses))
        .order_by(StagedRow.row_id)))


def _chunks(rows: list, size: int = CHUNK) -> list[list]:
    return [rows[i:i + size] for i in range(0, len(rows), size)]


def _posting(session, run_id: int, step_key: str) -> Posting | None:
    return session.scalar(select(Posting).where(Posting.run_id == run_id, Posting.step_key == step_key))


def _mark_done(session, run_id: int, module_code: str, step_key: str, user_id: int, out: dict, row_ids: list[int]) -> None:
    p = _posting(session, run_id, step_key)
    if p is None:
        p = Posting(run_id=run_id, module_code=module_code, step_key=step_key, attempts=0)
        session.add(p)
    p.status_code, p.message, p.user_id, p.finished_at = "DONE", None, user_id, c.now()
    p.attempts = (p.attempts or 0) + 1
    p.target_type, p.target_id = out.get("target_type"), out.get("target_id")
    p.journal_entry_id, p.row_count, p.amount = out.get("journal_entry_id"), len(row_ids), c.money(out.get("amount"))
    per_row = out.get("rows", {})
    for r in session.scalars(select(StagedRow).where(StagedRow.row_id.in_(row_ids))):
        target_type, target_id, je = per_row.get(r.row_id, (out.get("target_type"), out.get("target_id"),
                                                             out.get("journal_entry_id")))
        r.status_code, r.errors, r.posted_at = "POSTED", None, c.now()
        r.target_type, r.target_id, r.journal_entry_id = target_type, target_id, je
        r.updated_by_user_id, r.updated_at = user_id, c.now()


def _mark_failed(run_id: int, module_code: str, step_key: str, user_id: int, row_ids: list[int], error: Exception) -> str:
    msg = str(error) if isinstance(error, ValueError) else f"خطای سیستمی: {type(error).__name__}: {error}"
    with new_session() as session:
        p = _posting(session, run_id, step_key)
        if p is None:
            p = Posting(run_id=run_id, module_code=module_code, step_key=step_key, attempts=0)
            session.add(p)
        if p.status_code != "DONE":
            p.status_code = "FAILED"
        p.message, p.user_id, p.finished_at, p.row_count = msg[:2000], user_id, c.now(), len(row_ids)
        p.attempts = (p.attempts or 0) + 1
        for r in session.scalars(select(StagedRow).where(StagedRow.row_id.in_(row_ids), StagedRow.status_code != "POSTED")):
            r.status_code, r.errors = "FAILED", [{"col": "", "label": "ثبت قطعی", "msg": msg[:500]}]
            r.updated_by_user_id, r.updated_at = user_id, c.now()
        c.event(session, run_id, "POST_FAIL", user_id, module_code, msg[:1000], {"step": step_key, "rows": len(row_ids)})
        session.commit()
    return msg


def _step(run_id: int, module_code: str, step_key: str, user_id: int, row_ids: list[int], work) -> tuple[str, str | None]:
    """گام درون‌تراکنشی: work(session) سند رسمی را می‌سازد و dict خروجی می‌دهد؛ همه با هم commit می‌شوند."""
    error = None
    with new_session() as session:
        p = _posting(session, run_id, step_key)
        if p is not None and p.status_code == "DONE":
            return "SKIPPED", None
        try:
            out = work(session)
            _mark_done(session, run_id, module_code, step_key, user_id, out, row_ids)
            session.commit()
            return "DONE", None
        except Exception as exc:  # noqa: BLE001 — خطا در گام ثبت می‌شود و بقیهٔ گام‌ها ادامه می‌دهند
            session.rollback()
            error = exc
    return "FAILED", _mark_failed(run_id, module_code, step_key, user_id, row_ids, error)


# --- آماده‌سازی و پایان ------------------------------------------------------------------------------------
def _prepare(company_id: int, user_id: int, run_id: int, module_code: str, difference_reason: str | None) -> dict:
    with new_session() as session:
        run = runs._run(session, company_id, run_id, lock=True)
        if run.kind_code == "CORRECTION":
            c.require(company_id, user_id, c.FORM_CORRECT)
            if session.get(OpeningRun, run.corrects_run_id).status_code != "LOCKED":
                raise ValueError("افتتاحیهٔ اصلاحی پس از قفل افتتاحیهٔ اصلی ثبت می‌شود.")
        if run.status_code not in ("IN_PROGRESS", "POSTING"):
            raise ValueError(f"فرایند در وضعیت «{c.RUN_STATUS_LABELS[run.status_code]}» است و ثبت قطعی نمی‌شود.")
        m = runs._module(session, run_id, module_code, lock=True)
        if m.status_code in _DONE_MODULE:
            raise ValueError("این ماژول قبلاً ثبت قطعی شده است.")
        if m.status_code not in ("APPROVED", "POSTING"):
            raise ValueError("فقط ماژول تأییدشده ثبت قطعی می‌شود.")
        if c.clearing_account_id(company_id) is None:
            raise ValueError("«حساب واسط افتتاحیه» در تنظیمات افتتاحیه مشخص نشده است.")
        if session.scalar(select(func.count()).select_from(StagedRow).where(
                StagedRow.run_id == run_id, StagedRow.module_code == module_code, StagedRow.status_code == "INVALID")):
            raise ValueError("ردیف دارای خطا وجود دارد؛ ماژول را به ورود اطلاعات برگردانید و اصلاح کنید.")
        info: dict = {}
        if module_code == "GL":
            pending = [x.module_code for x in session.scalars(select(RunModule).where(RunModule.run_id == run_id))
                       if x.module_code != "GL" and not _module_done(session, x)]
            if pending:
                raise ValueError("سند تراز افتتاحیه آخر از همه ثبت می‌شود؛ ابتدا این ماژول‌ها را ثبت کنید: "
                                 + "، ".join(c.MODULE_LABELS[x] for x in pending))
            info = _gl_plan(session, company_id, run, difference_reason, user_id)
        m.status_code = "POSTING"
        run.status_code = "POSTING"
        c.event(session, run_id, "POST", user_id, module_code, "شروع ثبت قطعی")
        session.commit()
        return info


def _module_done(session, m: RunModule) -> bool:
    if m.status_code in _DONE_MODULE:
        return True
    return m.status_code == "NOT_STARTED" and not session.scalar(select(func.count()).select_from(StagedRow).where(
        StagedRow.run_id == m.run_id, StagedRow.module_code == m.module_code))


def _finish(company_id: int, user_id: int, run_id: int, module_code: str, failed: list[str]) -> str:
    with new_session() as session:
        run = runs._run(session, company_id, run_id, lock=True)
        m = runs._module(session, run_id, module_code, lock=True)
        left = session.scalar(select(func.count()).select_from(StagedRow).where(
            StagedRow.run_id == run_id, StagedRow.module_code == module_code, StagedRow.status_code.in_(("VALID", "FAILED"))))
        if not left and not failed:
            m.status_code, m.posted_at = "POSTED", c.now()
            posted = session.scalar(select(func.count()).select_from(StagedRow).where(
                StagedRow.run_id == run_id, StagedRow.module_code == module_code, StagedRow.status_code == "POSTED"))
            c.event(session, run_id, "POST", user_id, module_code, "ثبت قطعی کامل شد", {"rows": posted})
            c.audit(session, company_id, user_id, run_id, "POST", {"module": module_code, "rows": posted})
            mods = list(session.scalars(select(RunModule).where(RunModule.run_id == run_id)))
            if all(_module_done(session, x) for x in mods):
                for x in mods:
                    if x.status_code not in _DONE_MODULE:  # ماژول بدون ردیف (مثلاً فقط برگشت در اصلاحیه)
                        x.status_code, x.posted_at = "POSTED", c.now()
                run.status_code, run.posted_by_user_id, run.posted_at = "POSTED", user_id, c.now()
        session.commit()
        return m.status_code


def post_module(company_id: int, user_id: int, run_id: int, module_code: str,
                difference_reason: str | None = None) -> SimpleNamespace:
    """ثبت قطعی یک ماژول تأییدشده؛ اجرای دوباره ادامهٔ گام‌های ناتمام است."""
    c.require(company_id, user_id, c.FORM_POST)
    if module_code not in c.MODULE_LABELS:
        raise ValueError("ماژول نامعتبر است.")
    with _ModuleLock(run_id, module_code):
        info = _prepare(company_id, user_id, run_id, module_code, difference_reason)
        with new_session() as session:
            run = session.get(OpeningRun, run_id)
            session.expunge(run)
        outcomes = _POSTERS[module_code](company_id, user_id, run, info)
        failed = [msg for status, msg in outcomes if status == "FAILED"]
        status = _finish(company_id, user_id, run_id, module_code, failed)
    return SimpleNamespace(module_status=status, done=sum(1 for s, _ in outcomes if s == "DONE"),
                           skipped=sum(1 for s, _ in outcomes if s == "SKIPPED"), failed=failed)


def return_failed_to_entry(company_id: int, user_id: int, run_id: int, module_code: str, comment: str | None = None) -> None:
    """ماژولی که بخشی از ردیف‌هایش ثبت نشده (خطای ثبت)، برای اصلاح همان ردیف‌ها به ورود اطلاعات برمی‌گردد؛
    ردیف‌های ثبت‌شده دست نمی‌خورند و پس از تأیید دوباره فقط باقی‌مانده ثبت می‌شود."""
    c.require(company_id, user_id, c.FORM_POST)
    with new_session() as session:
        run = runs._run(session, company_id, run_id, lock=True)
        m = runs._module(session, run_id, module_code, lock=True)
        if m.status_code != "POSTING":
            raise ValueError("فقط ماژولی که ثبتش ناتمام مانده به ورود اطلاعات برمی‌گردد.")
        if not session.scalar(select(func.count()).select_from(StagedRow).where(
                StagedRow.run_id == run_id, StagedRow.module_code == module_code, StagedRow.status_code == "FAILED")):
            raise ValueError("ردیف ناموفقی برای اصلاح وجود ندارد؛ ثبت را دوباره اجرا کنید.")
        m.status_code = "HAS_ERRORS"
        m.submitted_at = m.approved_at = None
        m.submitted_by_user_id = m.approved_by_user_id = None
        if run.status_code == "POSTING" and not session.scalar(select(func.count()).select_from(RunModule).where(
                RunModule.run_id == run_id, RunModule.status_code.in_(("POSTING", "POSTED")))):
            run.status_code = "IN_PROGRESS"
        c.event(session, run_id, "RESET", user_id, module_code, comment or "بازگشت ردیف‌های ناموفق برای اصلاح")
        session.commit()


# --- دفتر کل ------------------------------------------------------------------------------------------------
def _gl_plan(session, company_id: int, run: OpeningRun, difference_reason: str | None, user_id: int) -> dict:
    """کنترل تراز و اختلاف تطبیق پیش از ثبت سند تراز؛ سیاست BLOCK ثبت را می‌بندد."""
    rows = _rows(session, run.run_id, "GL", ("VALID", "FAILED"))
    debit = sum((_d(r.resolved["base_debit"]) for r in rows), c.ZERO)
    credit = sum((_d(r.resolved["base_credit"]) for r in rows), c.ZERO)
    if debit != credit:
        raise ValueError(f"تراز افتتاحیه تراز نیست: جمع بدهکار {debit:,} و جمع بستانکار {credit:,} "
                         f"(اختلاف {debit - credit:,}).")
    rec = reconcile.compute(session, company_id, run.run_id)
    residual = rec.projected_clearing
    if residual == 0:
        return {"residual": c.ZERO}
    detail = "؛ ".join(f"{x.account} {x.counterparty}: {x.difference:,}" for x in rec.rows if x.difference)[:1500]
    policy = c.settings(company_id, session)
    if policy.difference_policy != "APPROVAL":
        raise ValueError(f"زیرسیستم‌ها با تراز افتتاحیه تطبیق ندارند (مانده حساب واسط پس از ثبت: {residual:,}). "
                         f"گزارش تطبیق را ببینید و اختلاف را رفع کنید. {detail}")
    if not (difference_reason or "").strip():
        raise ValueError(f"اختلاف تطبیق {residual:,} است؛ برای ثبت با اختلاف، دلیل را بنویسید.")
    c.require(company_id, user_id, c.FORM_DIFFERENCE)
    if policy.difference_account_id is None:
        raise ValueError("«حساب اختلاف افتتاحیه» در تنظیمات مشخص نشده است.")
    c.event(session, run.run_id, "DIFFERENCE", user_id, "GL", difference_reason.strip(),
            {"amount": residual, "detail": detail})
    c.audit(session, company_id, user_id, run.run_id, "DIFFERENCE", {"amount": str(residual), "reason": difference_reason})
    return {"residual": residual, "difference_account_id": policy.difference_account_id, "reason": difference_reason.strip()}


def _post_gl(company_id: int, user_id: int, run: OpeningRun, info: dict) -> list:
    from peecha.services import journal_entries as je_service

    clearing = c.clearing_account_id(company_id)
    with new_session() as session:
        rows = _rows(session, run.run_id, "GL")
        ctrl = reconcile.control_accounts(session, company_id, run.run_id)
        base_currency = run.currency_id
        row_ids = [r.row_id for r in rows]
        lines, to_clearing = [], {}
        for r in rows:
            res = r.resolved
            acc = res["account_id"]
            if acc in ctrl:
                to_clearing[acc] = to_clearing.get(acc, c.ZERO) + _d(res["base_debit"]) - _d(res["base_credit"])
                continue
            foreign = int(res["currency_id"]) != base_currency
            lines.append(je_service.LineInput(
                account_id=acc, description=res.get("description") or f"افتتاحیه {run.code}",
                debit=_d(res["debit"]), credit=_d(res["credit"]), details={int(k): v for k, v in (res.get("details") or {}).items()},
                currency_id=int(res["currency_id"]) if foreign else None, exchange_rate=_d(res["rate"]) if foreign else None))
        codes = reconcile.account_codes(company_id, list(to_clearing))
    for acc, amount in to_clearing.items():
        if amount:
            lines.append(je_service.LineInput(
                account_id=clearing, description=f"سهم حساب کنترل {codes.get(acc, acc)} ({c.MODULE_LABELS[ctrl[acc]]})",
                debit=amount if amount > 0 else c.ZERO, credit=-amount if amount < 0 else c.ZERO))
    residual = info.get("residual") or c.ZERO
    if residual:
        lines.append(je_service.LineInput(account_id=clearing, description="انتقال اختلاف تطبیق (با مجوز)",
                                          debit=-residual if residual < 0 else c.ZERO, credit=residual if residual > 0 else c.ZERO))
        lines.append(je_service.LineInput(account_id=info["difference_account_id"],
                                          description=f"اختلاف افتتاحیه: {info.get('reason', '')}"[:250],
                                          debit=residual if residual > 0 else c.ZERO, credit=-residual if residual < 0 else c.ZERO))

    def work(session):
        je = je_service.create_journal_entry(company_id, user_id, run.go_live_date, f"سند افتتاحیه — {run.title}", lines,
                                             alternative_number=f"OPN-{run.code}", entry_type_code="OPENING", session=session)
        return {"target_type": "JOURNAL_ENTRY", "target_id": je.journal_entry_id, "journal_entry_id": je.journal_entry_id,
                "amount": sum((ln.debit for ln in lines), c.ZERO)}
    if not rows:
        return []
    return [_step(run.run_id, "GL", f"GL:{run.run_id}", user_id, row_ids, work)]


# --- موجودی کالا ---------------------------------------------------------------------------------------------
def _post_inventory(company_id: int, user_id: int, run: OpeningRun, info: dict) -> list:
    from peecha.services import inventory_documents as inv_docs
    from peecha.services import lot_tracking

    with new_session() as session:
        rows = _rows(session, run.run_id, "INVENTORY")
        by_wh: dict[int, list] = {}
        for r in rows:
            by_wh.setdefault(int(r.resolved["warehouse_id"]), []).append((r.row_id, dict(r.resolved)))
    outcomes = []
    for wh, items in sorted(by_wh.items()):
        for part in _chunks(items):
            ids = [rid for rid, _ in part]

            def work(session, part=part, wh=wh):
                lines, tracking = [], {}
                for i, (_rid, res) in enumerate(part):
                    qty, qty_base = _d(res["quantity"]), _d(res["quantity_base"])
                    lines.append(inv_docs.LineFields(
                        item_id=int(res["item_id"]), uom_id=int(res["uom_id"]), quantity=qty, quantity_base=qty_base,
                        bin_location_id=res.get("bin_location_id"), unit_cost=_d(res["unit_cost_base"]),
                        description="موجودی افتتاحیه"))
                    if res.get("batch_no") or res.get("serial_no") or res.get("expiry_date"):
                        tracking[i] = [lot_tracking.TrackingEntry(
                            quantity=qty_base, batch_no=res.get("batch_no"), serial_no=res.get("serial_no"),
                            expiry_date=_date(res.get("expiry_date")), manufacture_date=_date(res.get("manufacture_date")))]
                result, line_ids = inv_docs.create_and_post_in_session(
                    session, company_id, user_id, "RECEIPT", run.go_live_date,
                    inv_docs.DocumentHeaderFields(destination_warehouse_id=wh, reference_no=f"OPN-{run.code}",
                                                  description=f"موجودی افتتاحیه — {run.title}"),
                    lines, role_overrides={"INVENTORY_ADJUSTMENT_GAIN": c.CLEARING_KEY}, tracking=tracking)
                return {"target_type": "STOCK_DOCUMENT", "target_id": result.stock_document_id,
                        "journal_entry_id": result.journal_entry_id,
                        "amount": sum((_d(res["quantity_base"]) * _d(res["unit_cost_base"]) for _r, res in part), c.ZERO)}
            outcomes.append(_step(run.run_id, "INVENTORY", f"INV:{wh}:{ids[0]}", user_id, ids, work))
    return outcomes


# --- دریافتنی / پرداختنی (سند باز افتتاحیه) ---------------------------------------------------------------
def _post_open_items(company_id: int, user_id: int, run: OpeningRun, module_code: str) -> list:
    from peecha.services import commercial_settlements as settlements
    from peecha.services import detail_dimensions as dims
    from peecha.services import journal_entries as je_service

    receivable = module_code == "RECEIVABLES"
    doc_type = "OPENING_RECEIVABLE" if receivable else "OPENING_PAYABLE"
    clearing = c.clearing_account_id(company_id)
    person_type = dims.get_person_dimension_type_id(company_id)
    cc_type = dims.get_specialized_dimension_type_id(company_id, dims.COST_CENTER_CODE)
    pj_type = dims.get_specialized_dimension_type_id(company_id, dims.PROJECT_CODE)
    with new_session() as session:
        rows = [(r.row_id, dict(r.resolved)) for r in _rows(session, run.run_id, module_code)]
    outcomes = []
    for part in _chunks(rows):
        ids = [rid for rid, _ in part]

        def work(session, part=part):
            docs, lines, clearing_total = {}, [], c.ZERO
            for rid, res in part:
                cur, rate = int(res["currency_id"]), _d(res["rate"])
                foreign = cur != run.currency_id
                open_amount = _d(res["open"])
                doc_id = settlements.create_opening_open_item(
                    session, company_id, user_id, doc_type, run.go_live_date, int(res["counterparty_id"]), cur, rate,
                    _d(res["original"]), _d(res["settled"]), _date(res.get("due_date")), res.get("legacy_no") or "",
                    legacy_date=_date(res.get("doc_date")),
                    description=" — ".join(x for x in (res.get("legacy_type"), res.get("description"),
                                                       "مورد اختلاف" if res.get("disputed") else None) if x) or None,
                    cost_center_detail_account_id=res.get("cost_center_id"), project_detail_account_id=res.get("project_id"),
                    branch_id=res.get("branch_id"))
                docs[rid] = doc_id
                details = {person_type: int(res["counterparty_id"])}
                if res.get("cost_center_id"):
                    details[cc_type] = res["cost_center_id"]
                if res.get("project_id"):
                    details[pj_type] = res["project_id"]
                memo = f"سند باز افتتاحیه {res.get('legacy_no') or ''}".strip()
                lines.append(je_service.LineInput(
                    account_id=int(res["account_id"]), description=memo, details=details,
                    debit=open_amount if receivable else c.ZERO, credit=c.ZERO if receivable else open_amount,
                    currency_id=cur if foreign else None, exchange_rate=rate if foreign else None))
                clearing_total += je_service._base_amount(open_amount, rate if foreign else decimal.Decimal(1))
            lines.append(je_service.LineInput(
                account_id=clearing, description=f"{c.MODULE_LABELS[module_code]} افتتاحیه — طرف مقابل",
                debit=c.ZERO if receivable else clearing_total, credit=clearing_total if receivable else c.ZERO))
            je = je_service.create_journal_entry(company_id, user_id, run.go_live_date,
                                                 f"{c.MODULE_LABELS[module_code]} افتتاحیه — {run.title}", lines,
                                                 alternative_number=f"OPN-{run.code}", entry_type_code="OPENING",
                                                 session=session).journal_entry_id
            from peecha.db.models.commercial import CommercialDocument

            for doc in session.scalars(select(CommercialDocument).where(CommercialDocument.document_id.in_(docs.values()))):
                doc.journal_entry_id = je
            return {"target_type": "JOURNAL_ENTRY", "target_id": je, "journal_entry_id": je, "amount": clearing_total,
                    "rows": {rid: ("COMMERCIAL_DOCUMENT", doc_id, je) for rid, doc_id in docs.items()}}
        outcomes.append(_step(run.run_id, module_code, f"{module_code}:{ids[0]}", user_id, ids, work))
    return outcomes


def _post_receivables(company_id, user_id, run, info):
    return _post_open_items(company_id, user_id, run, "RECEIVABLES")


def _post_payables(company_id, user_id, run, info):
    return _post_open_items(company_id, user_id, run, "PAYABLES")


# --- چک‌های باز (سرویس خزانه، خودش commit می‌کند) ---------------------------------------------------------
def _cheque_lookup(session, company_id: int, marker: str, kind: str):
    """(سند، چک) ساخته‌شده با همین نشانه؛ سند برگشت‌خورده/باطل حساب نمی‌شود."""
    from peecha.db.models.accounting import JournalEntry, JournalEntryStatus
    from peecha.db.models.treasury import IssuedCheck, ReceivedCheck

    live = select(JournalEntryStatus.status_id).where(JournalEntryStatus.code.in_(("TEMPORARY", "PERMANENT", "DRAFT")))
    je = session.scalar(select(JournalEntry.journal_entry_id).where(
        JournalEntry.company_id == company_id, JournalEntry.alternative_number == marker, JournalEntry.status_id.in_(live)))
    if je is None:
        return None, None
    model = ReceivedCheck if kind == "RECEIVED" else IssuedCheck
    pk = model.received_check_id if kind == "RECEIVED" else model.issued_check_id
    return je, session.scalar(select(pk).where(model.source_journal_entry_id == je))


def _post_cheques(company_id: int, user_id: int, run: OpeningRun, info: dict) -> list:
    from peecha.services import detail_dimensions as dims
    from peecha.services import journal_entries as je_service
    from peecha.services import treasury

    clearing = c.clearing_account_id(company_id)
    person_type = dims.get_person_dimension_type_id(company_id)
    with new_session() as session:
        rows = [(r.row_id, dict(r.resolved)) for r in _rows(session, run.run_id, "CHEQUES")]
    outcomes = []
    for rid, res in rows:
        step_key, marker, kind = f"CHQ:{rid}", f"OPN{run.run_id}-CHQ{rid}", res["kind"]
        try:
            with new_session() as session:
                p = _posting(session, run.run_id, step_key)
                if p is not None and p.status_code == "DONE":
                    outcomes.append(("SKIPPED", None))
                    continue
                je, check_id = _cheque_lookup(session, company_id, marker, kind)
                if p is None:
                    p = Posting(run_id=run.run_id, module_code="CHEQUES", step_key=step_key, attempts=0)
                    session.add(p)
                p.status_code, p.user_id = "PENDING", user_id
                session.commit()
            if je is not None and check_id is None:
                # سند ساخته شده ولی چک نه (قطع میان دو commit سرویس خزانه): سند ناقص برگشت می‌خورد و از نو ساخته می‌شود
                je_service.reverse_journal_entry(je, company_id, user_id)
                je = None
            if je is None:
                amount = _d(res["amount"])
                entry = {"check_no": res["cheque_no"], "amount": amount, "due_date": _date(res["due_date"])}
                if kind == "RECEIVED":
                    entry.update(check_bank_name=res.get("bank_name"), party_name=res.get("party_name"),
                                 check_serial=res.get("sayad_no"))
                else:
                    entry.update(payee_name=res.get("party_name"), sayad_no=res.get("sayad_no"))
                ml = treasury.MethodLine(method="CHECK", amount=amount, description=f"چک افتتاحیه {res['cheque_no']}",
                                         detail_account_id=res.get("holder_id"), check_no=res["cheque_no"],
                                         check_bank_name=res.get("bank_name"), check_due_date=_date(res["due_date"]),
                                         check_party_name=res.get("party_name"), checks=[entry])
                treasury.create_treasury_voucher(
                    company_id, user_id, "RECEIPT" if kind == "RECEIVED" else "PAYMENT", clearing,
                    {person_type: int(res["counterparty_id"])}, run.go_live_date,
                    f"چک باز افتتاحیه {res['cheque_no']} — {run.title}", [ml], alternative_number=marker,
                    entry_type_code="OPENING")
            with new_session() as session:
                je, check_id = _cheque_lookup(session, company_id, marker, kind)
                if je is None or check_id is None:
                    raise ValueError("سند چک پس از ثبت پیدا نشد.")
                _mark_done(session, run.run_id, "CHEQUES", step_key, user_id,
                           {"target_type": "RECEIVED_CHECK" if kind == "RECEIVED" else "ISSUED_CHECK", "target_id": check_id,
                            "journal_entry_id": je, "amount": _d(res["amount"])}, [rid])
                session.commit()
            outcomes.append(("DONE", None))
        except Exception as exc:  # noqa: BLE001
            outcomes.append(("FAILED", _mark_failed(run.run_id, "CHEQUES", step_key, user_id, [rid], exc)))
    return outcomes


# --- دارایی ثابت ------------------------------------------------------------------------------------------------
def _post_fixed_assets(company_id: int, user_id: int, run: OpeningRun, info: dict) -> list:
    from peecha.services.fixed_assets import assets as fa_assets
    from peecha.services.fixed_assets import common as fac

    clearing = c.clearing_account_id(company_id)
    with new_session() as session:
        rows = [(r.row_id, dict(r.resolved)) for r in _rows(session, run.run_id, "FIXED_ASSETS")]
        codes = {r.row_id: r.row_key for r in _rows(session, run.run_id, "FIXED_ASSETS")}
    outcomes = []
    for part in _chunks(rows, 100):
        ids = [rid for rid, _ in part]

        def work(session, part=part):
            book = fac.primary_book(session, company_id)
            jlines, txns, per_row, total = [], [], {}, c.ZERO
            for rid, res in part:
                start = _date(res.get("start"))
                cost, accum = _d(res["cost"]), _d(res["accumulated"])
                asset = fa_assets.insert_asset(session, company_id, user_id, fa_assets.AssetFields(
                    asset_code=codes[rid], name=res["name"], category_id=int(res["category_id"]), source_code="OPENING",
                    acquisition_date=_date(res.get("acquisition_date")) or start, residual_value=_d(res["residual"]),
                    useful_life=_d(res["life_months"]) if res.get("life_months") else None, useful_life_unit="MONTH",
                    depreciation_method=res["method"], branch_id=res.get("branch_id"),
                    cost_center_detail_account_id=res.get("cost_center_id"), project_detail_account_id=res.get("project_id"),
                    location_id=res.get("location_id"), serial_no=res.get("serial_no"),
                    notes=f"افتتاحیه {run.code}: استهلاک انباشته تا {c.fmt_date(run.balance_date)}"), status=res["status"])
                asset.capitalization_date = asset.in_service_date = start or run.go_live_date
                asset.depreciation_start_date = start if res["method"] != "NONE" else None
                asset.depreciated_months_offset = int(res.get("elapsed_months") or 0)
                asset.purchase_price = cost
                txns.append((asset, cost, accum))
                dets = (asset.cost_center_detail_account_id, asset.project_detail_account_id, fac.asset_detail_id(asset))
                jlines.append(fac.JLine(int(res["asset_account_id"]), debit=cost, detail_ids=dets,
                                        description=f"بهای دارایی {asset.asset_code} (افتتاحیه)"))
                if accum:
                    jlines.append(fac.JLine(int(res["accum_account_id"]), credit=accum, detail_ids=dets,
                                            description=f"استهلاک انباشتهٔ {asset.asset_code} (افتتاحیه)"))
                total += cost - accum
                per_row[rid] = ("FIXED_ASSET", asset.asset_id, None)
            jlines.append(fac.JLine(clearing, credit=total, description="دارایی ثابت افتتاحیه — طرف مقابل"))
            je = fac.post_journal(session, company_id, user_id, run.go_live_date, f"دارایی ثابت افتتاحیه — {run.title}", jlines)
            for asset, cost, accum in txns:  # دفتر دارایی تغییرناپذیر است؛ شمارهٔ سند همان لحظهٔ درج داده می‌شود
                fac.record_txn(session, asset, book.book_id, "OPENING", run.go_live_date, cost=cost, depreciation=accum,
                               description=f"افتتاحیه {run.code}", reference=f"OPN-{run.code}", journal_entry_id=je,
                               source_type="OPENING_RUN", source_id=run.run_id, user_id=user_id)
            return {"target_type": "JOURNAL_ENTRY", "target_id": je, "journal_entry_id": je, "amount": total,
                    "rows": {rid: (tt, tid, je) for rid, (tt, tid, _x) in per_row.items()}}
        outcomes.append(_step(run.run_id, "FIXED_ASSETS", f"FA:{ids[0]}", user_id, ids, work))
    return outcomes


def _post_wip(company_id: int, user_id: int, run: OpeningRun, info: dict) -> list:
    from peecha.services.opening import wip

    return wip.post(company_id, user_id, run, _step, _rows)


_POSTERS = {"GL": _post_gl, "INVENTORY": _post_inventory, "RECEIVABLES": _post_receivables, "PAYABLES": _post_payables,
            "CHEQUES": _post_cheques, "FIXED_ASSETS": _post_fixed_assets, "WIP": _post_wip}
