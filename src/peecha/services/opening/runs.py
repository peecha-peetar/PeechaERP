"""فرایند افتتاحیه (R314): تعریف، ماژول‌ها و مسئولان، گردش وضعیت هر ماژول، درصد پیشرفت و لغو.

هر ماژول: شروع‌نشده ← در حال ورود (یا دارای خطا) ← آمادهٔ بررسی ← تأییدشده ← در حال ثبت ← ثبت قطعی ← قفل‌شده.
ورود دوبارهٔ اطلاعات پس از ارسال/تأیید، ماژول را به «در حال ورود» برمی‌گرداند (تأیید باید دوباره انجام شود).
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from peecha.db.base import new_session
from peecha.db.models.accounting import FiscalYear
from peecha.db.models.core import Company
from peecha.db.models.opening import ImportBatch, OpeningEvent, OpeningRun, Posting, RunModule, StagedRow
from peecha.services.opening import common as c

EDITABLE_RUN = ("DRAFT", "IN_PROGRESS")
ENTRY_RUN = EDITABLE_RUN + ("POSTING",)  # ماژول ثبت‌نشده در فرایند نیمه‌ثبت‌شده هنوز ورود/ارسال می‌پذیرد
LOCKED_MODULE = ("POSTING", "POSTED", "LOCKED")


def _run(session, company_id: int, run_id: int, lock: bool = False) -> OpeningRun:
    q = select(OpeningRun).where(OpeningRun.run_id == run_id)
    if lock:
        q = q.with_for_update()
    run = session.scalar(q)
    if run is None or run.company_id != company_id:
        raise ValueError("فرایند افتتاحیه نامعتبر است.")
    return run


def _module(session, run_id: int, module_code: str, lock: bool = False) -> RunModule:
    q = select(RunModule).where(RunModule.run_id == run_id, RunModule.module_code == module_code)
    if lock:
        q = q.with_for_update()
    m = session.scalar(q)
    if m is None:
        raise ValueError(f"ماژول «{c.MODULE_LABELS.get(module_code, module_code)}» در این فرایند انتخاب نشده است.")
    return m


def _require_setup(session, company_id: int, user_id: int, run_id: int) -> None:
    """تعریف/مسئولان فرایند اصلی با دسترسی «تعریف»، فرایند اصلاحی با دسترسی «اصلاح»."""
    kind = session.scalar(select(OpeningRun.kind_code).where(OpeningRun.run_id == run_id))
    c.require(company_id, user_id, c.FORM_CORRECT if kind == "CORRECTION" else c.FORM_SETUP)


def _posted_rows(session, run_id: int, module_code: str | None = None) -> int:
    q = select(func.count()).select_from(StagedRow).where(StagedRow.run_id == run_id, StagedRow.status_code == "POSTED")
    if module_code:
        q = q.where(StagedRow.module_code == module_code)
    return session.scalar(q) or 0


def create_run(company_id: int, user_id: int, code: str, title: str, fiscal_year_id: int, balance_date: datetime.date,
               modules: list[str], go_live_date: datetime.date | None = None, notes: str | None = None,
               corrects_run_id: int | None = None) -> int:
    """فرایند تازه؛ برای هر شرکت و سال مالی یک افتتاحیهٔ اصلی (تکرار فقط با فرایند اصلاحی)."""
    c.require(company_id, user_id, c.FORM_CORRECT if corrects_run_id else c.FORM_SETUP)
    code, title = (code or "").strip(), (title or "").strip()
    if not code or not title:
        raise ValueError("کد و عنوان فرایند الزامی است.")
    bad = [m for m in modules if m not in c.MODULE_LABELS]
    if bad or not modules:
        raise ValueError("حداقل یک ماژول معتبر انتخاب کنید.")
    go_live_date = go_live_date or (balance_date + datetime.timedelta(days=1))
    if go_live_date <= balance_date:
        raise ValueError("تاریخ شروع عملیات باید بعد از تاریخ مانده‌ها باشد.")
    with new_session() as session:
        fy = session.get(FiscalYear, fiscal_year_id)
        if fy is None or fy.company_id != company_id:
            raise ValueError("سال مالی نامعتبر است.")
        if fy.is_closed:
            raise ValueError("سال مالی بسته است؛ افتتاحیه در سال بسته ثبت نمی‌شود.")
        if not (fy.start_date <= go_live_date <= fy.end_date):
            raise ValueError("تاریخ شروع عملیات (تاریخ اسناد افتتاحیه) باید در همان سال مالی باشد.")
        kind = "ORIGINAL"
        if corrects_run_id:
            original = _run(session, company_id, corrects_run_id)
            if original.status_code not in ("POSTED", "LOCKED"):
                raise ValueError("افتتاحیهٔ اصلاحی فقط برای افتتاحیهٔ ثبت‌شده ساخته می‌شود.")
            kind, fiscal_year_id = "CORRECTION", original.fiscal_year_id
        company = session.get(Company, company_id)
        run = OpeningRun(company_id=company_id, fiscal_year_id=fiscal_year_id, code=code, title=title, kind_code=kind,
                         corrects_run_id=corrects_run_id, balance_date=balance_date, go_live_date=go_live_date,
                         currency_id=company.base_currency_id, status_code="DRAFT", notes=notes or None,
                         created_by_user_id=user_id)
        session.add(run)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            if "ux_opn_runs_original" in str(exc.orig):
                raise ValueError("برای این شرکت و سال مالی افتتاحیهٔ اصلی وجود دارد؛ تغییر فقط با افتتاحیهٔ اصلاحی ممکن است.") from exc
            raise ValueError("کد فرایند تکراری است.") from exc
        for m in dict.fromkeys(modules):
            session.add(RunModule(run_id=run.run_id, module_code=m, status_code="NOT_STARTED"))
        c.event(session, run.run_id, "CORRECTION" if corrects_run_id else "CREATE", user_id,
                details={"modules": list(modules), "balance_date": balance_date, "go_live_date": go_live_date})
        c.audit(session, company_id, user_id, run.run_id, "CREATE", {"code": code, "modules": list(modules)})
        session.commit()
        return run.run_id


def update_run(company_id: int, user_id: int, run_id: int, title: str, balance_date: datetime.date,
               go_live_date: datetime.date, notes: str | None = None) -> None:
    if go_live_date <= balance_date:
        raise ValueError("تاریخ شروع عملیات باید بعد از تاریخ مانده‌ها باشد.")
    with new_session() as session:
        _require_setup(session, company_id, user_id, run_id)
        run = _run(session, company_id, run_id, lock=True)
        if run.status_code not in EDITABLE_RUN or _posted_rows(session, run_id):
            raise ValueError("پس از شروع ثبت قطعی، مشخصات فرایند تغییر نمی‌کند.")
        fy = session.get(FiscalYear, run.fiscal_year_id)
        if not (fy.start_date <= go_live_date <= fy.end_date):
            raise ValueError("تاریخ شروع عملیات باید در همان سال مالی باشد.")
        before = {"title": run.title, "balance_date": run.balance_date, "go_live_date": run.go_live_date}
        run.title, run.balance_date, run.go_live_date, run.notes = (title or run.title).strip(), balance_date, go_live_date, notes
        c.event(session, run_id, "UPDATE", user_id, details={"before": before})
        c.audit(session, company_id, user_id, run_id, "UPDATE", {"before": c.jsonable(before)})
        session.commit()


def set_modules(company_id: int, user_id: int, run_id: int, modules: list[str]) -> None:
    if not modules or any(m not in c.MODULE_LABELS for m in modules):
        raise ValueError("حداقل یک ماژول معتبر انتخاب کنید.")
    with new_session() as session:
        _require_setup(session, company_id, user_id, run_id)
        run = _run(session, company_id, run_id, lock=True)
        if run.status_code not in EDITABLE_RUN:
            raise ValueError("ماژول‌ها فقط پیش از ثبت قطعی تغییر می‌کنند.")
        current = {m.module_code: m for m in session.scalars(select(RunModule).where(RunModule.run_id == run_id))}
        for code, m in current.items():
            if code not in modules:
                if session.scalar(select(func.count()).select_from(StagedRow).where(
                        StagedRow.run_id == run_id, StagedRow.module_code == code)):
                    raise ValueError(f"ماژول «{c.MODULE_LABELS[code]}» اطلاعات واردشده دارد؛ اول ردیف‌هایش را حذف کنید.")
                session.delete(m)
        for code in modules:
            if code not in current:
                session.add(RunModule(run_id=run_id, module_code=code, status_code="NOT_STARTED"))
        c.event(session, run_id, "MODULES", user_id, details={"modules": modules})
        session.commit()


def set_people(company_id: int, user_id: int, run_id: int, module_code: str, owner_user_id: int | None,
               approver_user_id: int | None) -> None:
    if owner_user_id and approver_user_id and owner_user_id == approver_user_id and not c.is_on(company_id, c.OPN_SELF_APPROVAL):
        raise ValueError("مسئول ورود و تأییدکننده باید دو نفر متفاوت باشند.")
    with new_session() as session:
        _require_setup(session, company_id, user_id, run_id)
        _run(session, company_id, run_id)
        m = _module(session, run_id, module_code, lock=True)
        if m.status_code in LOCKED_MODULE:
            raise ValueError("ماژول ثبت‌شده مسئول جدید نمی‌گیرد.")
        m.owner_user_id, m.approver_user_id = owner_user_id, approver_user_id
        c.event(session, run_id, "PEOPLE", user_id, module_code, details={"owner": owner_user_id, "approver": approver_user_id})
        session.commit()


def refresh_module_status(session, run_id: int, module_code: str, user_id: int | None = None) -> str:
    """پس از ورود/حذف/اعتبارسنجی: وضعیت از روی ردیف‌ها. ماژول ارسال‌شده یا تأییدشده با تغییر داده به ورود برمی‌گردد."""
    m = _module(session, run_id, module_code, lock=True)
    if m.status_code in LOCKED_MODULE:
        return m.status_code
    counts = dict(session.execute(select(StagedRow.status_code, func.count()).where(
        StagedRow.run_id == run_id, StagedRow.module_code == module_code).group_by(StagedRow.status_code)).all())
    if m.status_code in ("READY", "APPROVED"):
        c.event(session, run_id, "RESET", user_id, module_code, "اطلاعات تغییر کرد؛ تأیید دوباره لازم است.")
        m.submitted_at = m.approved_at = None
        m.submitted_by_user_id = m.approved_by_user_id = None
    if not counts:
        m.status_code = "NOT_STARTED"
    elif counts.get("INVALID") or counts.get("FAILED"):
        m.status_code = "HAS_ERRORS"
    else:
        m.status_code = "ENTERING"
    run = session.get(OpeningRun, run_id)
    if run.status_code == "DRAFT" and counts:
        run.status_code = "IN_PROGRESS"
    return m.status_code


def submit(company_id: int, user_id: int, run_id: int, module_code: str, comment: str | None = None) -> None:
    """آماده برای بررسی: بدون ردیف دارای خطا."""
    c.require(company_id, user_id, c.FORM_ENTER)
    with new_session() as session:
        run = _run(session, company_id, run_id)
        if run.status_code not in ENTRY_RUN:
            raise ValueError("فرایند در وضعیت ورود اطلاعات نیست.")
        m = _module(session, run_id, module_code, lock=True)
        if m.status_code not in ("ENTERING",):
            raise ValueError("فقط ماژول در حال ورود و بدون خطا برای بررسی ارسال می‌شود."
                             if m.status_code != "HAS_ERRORS" else "ردیف‌های دارای خطا را اصلاح کنید، سپس ارسال کنید.")
        if m.owner_user_id and m.owner_user_id != user_id and not c.is_super_admin(user_id):
            raise ValueError("فقط مسئول ورود اطلاعات همین ماژول آن را ارسال می‌کند.")
        m.status_code, m.submitted_by_user_id, m.submitted_at, m.reject_reason = "READY", user_id, c.now(), None
        c.event(session, run_id, "SUBMIT", user_id, module_code, comment)
        session.commit()


def approve(company_id: int, user_id: int, run_id: int, module_code: str, comment: str | None = None) -> None:
    c.require(company_id, user_id, c.FORM_APPROVE)
    with new_session() as session:
        _run(session, company_id, run_id)
        m = _module(session, run_id, module_code, lock=True)
        if m.status_code != "READY":
            raise ValueError("فقط ماژول «آمادهٔ بررسی» تأیید می‌شود.")
        if m.approver_user_id and m.approver_user_id != user_id and not c.is_super_admin(user_id):
            raise ValueError("تأییدکنندهٔ این ماژول کاربر دیگری است.")
        if user_id == m.submitted_by_user_id and not c.is_on(company_id, c.OPN_SELF_APPROVAL, session):
            raise ValueError("ارسال‌کنندهٔ اطلاعات خودش آن را تأیید نمی‌کند (تفکیک وظایف).")
        if session.scalar(select(func.count()).select_from(StagedRow).where(
                StagedRow.run_id == run_id, StagedRow.module_code == module_code, StagedRow.status_code == "INVALID")):
            raise ValueError("ردیف دارای خطا وجود دارد.")
        m.status_code, m.approved_by_user_id, m.approved_at = "APPROVED", user_id, c.now()
        c.event(session, run_id, "APPROVE", user_id, module_code, comment)
        c.audit(session, company_id, user_id, run_id, "APPROVE", {"module": module_code})
        session.commit()


def reject(company_id: int, user_id: int, run_id: int, module_code: str, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("دلیل رد را بنویسید.")
    c.require(company_id, user_id, c.FORM_APPROVE)
    with new_session() as session:
        _run(session, company_id, run_id)
        m = _module(session, run_id, module_code, lock=True)
        if m.status_code not in ("READY", "APPROVED"):
            raise ValueError("فقط ماژول ارسال‌شده یا تأییدشده رد می‌شود.")
        m.status_code, m.reject_reason = "ENTERING", reason.strip()
        m.approved_by_user_id = m.approved_at = None
        c.event(session, run_id, "REJECT", user_id, module_code, reason.strip())
        c.audit(session, company_id, user_id, run_id, "REJECT", {"module": module_code, "reason": reason})
        session.commit()


def cancel_run(company_id: int, user_id: int, run_id: int, reason: str) -> None:
    """فقط فرایندی که هیچ ردیفش ثبت قطعی نشده لغو می‌شود (برای ثبت‌شده: افتتاحیهٔ اصلاحی)."""
    if not (reason or "").strip():
        raise ValueError("دلیل لغو را بنویسید.")
    with new_session() as session:
        _require_setup(session, company_id, user_id, run_id)
        run = _run(session, company_id, run_id, lock=True)
        if run.status_code not in EDITABLE_RUN:
            raise ValueError("فرایند ثبت‌شده لغو نمی‌شود؛ افتتاحیهٔ اصلاحی بسازید.")
        if _posted_rows(session, run_id) or session.scalar(select(func.count()).select_from(Posting).where(
                Posting.run_id == run_id, Posting.status_code.in_(("PENDING", "DONE")))):
            raise ValueError("بخشی از این فرایند ثبت شده است؛ افتتاحیهٔ اصلاحی بسازید.")
        run.status_code, run.cancel_reason = "CANCELLED", reason.strip()
        c.event(session, run_id, "CANCEL", user_id, comment=reason.strip())
        c.audit(session, company_id, user_id, run_id, "CANCEL", {"reason": reason})
        session.commit()


# --- خواندن -------------------------------------------------------------------------------------------------
def list_runs(company_id: int, include_cancelled: bool = True) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(OpeningRun).where(OpeningRun.company_id == company_id).order_by(OpeningRun.run_id.desc())
        if not include_cancelled:
            q = q.where(OpeningRun.status_code != "CANCELLED")
        runs = list(session.scalars(q))
        fys = {f.fiscal_year_id: f.code for f in session.scalars(select(FiscalYear).where(FiscalYear.company_id == company_id))}
        progress = {r.run_id: _progress(session, r.run_id) for r in runs}
        return [SimpleNamespace(run_id=r.run_id, code=r.code, title=r.title, kind_code=r.kind_code,
                                kind_label=c.KIND_LABELS[r.kind_code], fiscal_year=fys.get(r.fiscal_year_id, ""),
                                balance_date=r.balance_date, go_live_date=r.go_live_date, status_code=r.status_code,
                                status_label=c.RUN_STATUS_LABELS[r.status_code], progress=progress[r.run_id][0],
                                corrects_run_id=r.corrects_run_id) for r in runs]


def _progress(session, run_id: int) -> tuple[int, list]:
    mods = list(session.scalars(select(RunModule).where(RunModule.run_id == run_id)))
    if not mods:
        return 0, mods
    return round(sum(c.MODULE_PROGRESS[m.status_code] for m in mods) / len(mods)), mods


def get_run(company_id: int, run_id: int) -> SimpleNamespace:
    with new_session() as session:
        r = _run(session, company_id, run_id)
        pct, mods = _progress(session, run_id)
        counts: dict[str, dict[str, int]] = {}
        amounts: dict[str, object] = {}
        for code, status, n, amt in session.execute(
                select(StagedRow.module_code, StagedRow.status_code, func.count(), func.coalesce(func.sum(StagedRow.amount), 0))
                .where(StagedRow.run_id == run_id).group_by(StagedRow.module_code, StagedRow.status_code)):
            counts.setdefault(code, {})[status] = n
            if status != "INVALID":
                amounts[code] = c.dec(amounts.get(code)) + c.dec(amt)
        names = c.user_names(session, [x for m in mods for x in (m.owner_user_id, m.approver_user_id, m.submitted_by_user_id,
                                                                 m.approved_by_user_id)] + [r.created_by_user_id])
        fy = session.get(FiscalYear, r.fiscal_year_id)
        order = {code: i for i, code in enumerate(c.POST_ORDER)}
        modules = []
        for m in sorted(mods, key=lambda x: order.get(x.module_code, 99)):
            cnt = counts.get(m.module_code, {})
            problems = []
            if cnt.get("INVALID"):
                problems.append(f"{cnt['INVALID']} ردیف دارای خطا")
            if cnt.get("FAILED"):
                problems.append(f"{cnt['FAILED']} ردیف با ثبت ناموفق")
            if not m.owner_user_id:
                problems.append("مسئول ورود تعیین نشده")
            if not m.approver_user_id:
                problems.append("تأییدکننده تعیین نشده")
            if m.status_code in ("NOT_STARTED",):
                problems.append("اطلاعاتی وارد نشده")
            modules.append(SimpleNamespace(
                module_code=m.module_code, label=c.MODULE_LABELS[m.module_code], status_code=m.status_code,
                status_label=c.MODULE_STATUS_LABELS[m.status_code], progress=c.MODULE_PROGRESS[m.status_code],
                owner_user_id=m.owner_user_id, owner=names.get(m.owner_user_id, ""), approver_user_id=m.approver_user_id,
                approver=names.get(m.approver_user_id, ""), submitted_by=names.get(m.submitted_by_user_id, ""),
                submitted_by_user_id=m.submitted_by_user_id, submitted_at=m.submitted_at,
                approved_by=names.get(m.approved_by_user_id, ""), approved_by_user_id=m.approved_by_user_id,
                approved_at=m.approved_at, posted_at=m.posted_at,
                reject_reason=m.reject_reason, total=sum(cnt.values()), valid=cnt.get("VALID", 0),
                invalid=cnt.get("INVALID", 0), posted=cnt.get("POSTED", 0), failed=cnt.get("FAILED", 0),
                amount=c.money(amounts.get(m.module_code)), problems=problems))
        events = list(session.scalars(select(OpeningEvent).where(OpeningEvent.run_id == run_id)
                                      .order_by(OpeningEvent.created_at.desc(), OpeningEvent.event_id.desc()).limit(300)))
        enames = c.user_names(session, [e.user_id for e in events])
        batches = list(session.scalars(select(ImportBatch).where(ImportBatch.run_id == run_id).order_by(ImportBatch.batch_id.desc())))
        bnames = c.user_names(session, [b.uploaded_by_user_id for b in batches])
        return SimpleNamespace(
            run_id=r.run_id, company_id=r.company_id, code=r.code, title=r.title, kind_code=r.kind_code,
            kind_label=c.KIND_LABELS[r.kind_code], corrects_run_id=r.corrects_run_id, fiscal_year_id=r.fiscal_year_id,
            fiscal_year=fy.code if fy else "", balance_date=r.balance_date, go_live_date=r.go_live_date, currency_id=r.currency_id,
            status_code=r.status_code, status_label=c.RUN_STATUS_LABELS[r.status_code], notes=r.notes, progress=pct,
            created_by=names.get(r.created_by_user_id, ""), created_at=r.created_at, posted_at=r.posted_at, locked_at=r.locked_at,
            modules=modules,
            events=[SimpleNamespace(at=e.created_at, code=e.event_code, label=c.EVENT_LABELS.get(e.event_code, e.event_code),
                                    module=c.MODULE_LABELS.get(e.module_code, "") if e.module_code else "",
                                    user=enames.get(e.user_id, ""), comment=e.comment or "", details=e.details or {})
                    for e in events],
            batches=[SimpleNamespace(batch_id=b.batch_id, module=c.MODULE_LABELS.get(b.module_code, b.module_code),
                                     module_code=b.module_code, version_no=b.version_no, source_code=b.source_code,
                                     file_name=b.file_name or ("ورود دستی" if b.source_code == "FORM" else ""),
                                     file_hash=b.file_hash or "", rows=b.row_count, valid=b.valid_count, invalid=b.invalid_count,
                                     skipped=b.posted_skipped, user=bnames.get(b.uploaded_by_user_id, ""), at=b.uploaded_at)
                     for b in batches])
