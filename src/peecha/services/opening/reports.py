"""R314 — گزارش‌های افتتاحیه روی همان موتور گزارش (گروه‌بندی، چاپ PDF، خروجی Excel).

تعریف‌ها (به ارز پایهٔ شرکت):
- تطبیق: برای هر حساب کنترل (دریافتنی/پرداختنی به تفکیک طرف‌حساب) «ماندهٔ تراز» = جمع ردیف‌های تراز افتتاحیه روی همان
  حساب (بدهکار +)، «جمع زیرسیستم» = اثر ردیف‌های زیرسیستم (پیش از ثبت) یا اثر واقعی سندهای ثبت‌شده؛ اختلاف = تراز − زیرسیستم.
- ماندهٔ باز سند افتتاحیه = مبلغ اصلی − همهٔ تسویه‌ها (تسویهٔ پیش از برش + تسویه‌های بعدی).
"""

from __future__ import annotations

import decimal

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.opening import ImportBatch, OpeningEvent, OpeningRun, Posting, RunModule, StagedRow
from peecha.services.opening import common as c
from peecha.services.purchase_reports import DATE, INT, MONEY, PERCENT, TEXT, ReportDef, ReportResult

_G = "افتتاحیه و انتقال اطلاعات"


def _opt(f, key, default=None):
    v = (f.options or {}).get(key)
    return default if v in (None, "ALL") else v


def _runs(session, company_id: int, f, include_cancelled: bool = False) -> list[OpeningRun]:
    q = select(OpeningRun).where(OpeningRun.company_id == company_id).order_by(OpeningRun.run_id)
    if not include_cancelled and _opt(f, "cancelled", "HIDE") == "HIDE":
        q = q.where(OpeningRun.status_code != "CANCELLED")
    return list(session.scalars(q))


_CANCELLED_OPT = ("cancelled", "فرایند لغوشده", (("HIDE", "نمایش داده نشود"), ("SHOW", "نمایش داده شود")))


def runs_report(company_id: int, f) -> ReportResult:
    from peecha.db.models.accounting import FiscalYear
    from peecha.services.opening import runs

    result = ReportResult([
        ("کد", TEXT), ("عنوان", TEXT), ("نوع", TEXT), ("سال مالی", TEXT), ("تاریخ مانده‌ها", DATE), ("شروع عملیات", DATE),
        ("وضعیت", TEXT), ("پیشرفت", PERCENT), ("ماژول‌ها", INT), ("ثبت قطعی", DATE), ("قفل", DATE), ("ایجادکننده", TEXT),
    ], no_total={7})
    with new_session() as session:
        fys = {y.fiscal_year_id: y.code for y in session.scalars(select(FiscalYear).where(FiscalYear.company_id == company_id))}
        items = _runs(session, company_id, f)
        names = c.user_names(session, [r.created_by_user_id for r in items])
        for r in items:
            pct, mods = runs._progress(session, r.run_id)
            result.add([r.code, r.title, c.KIND_LABELS[r.kind_code], fys.get(r.fiscal_year_id, ""), r.balance_date, r.go_live_date,
                        c.RUN_STATUS_LABELS[r.status_code], decimal.Decimal(pct), len(mods),
                        r.posted_at.date() if r.posted_at else None, r.locked_at.date() if r.locked_at else None,
                        names.get(r.created_by_user_id, "")])
    return result


def modules_report(company_id: int, f) -> ReportResult:
    from peecha.services.opening import runs

    result = ReportResult([
        ("فرایند", TEXT), ("ماژول", TEXT), ("وضعیت", TEXT), ("مسئول ورود", TEXT), ("تأییدکننده", TEXT), ("ارسال", TEXT),
        ("تأیید", TEXT), ("ردیف‌ها", INT), ("معتبر", INT), ("دارای خطا", INT), ("ثبت‌شده", INT), ("ناموفق", INT),
        ("مبلغ", MONEY), ("مشکلات", TEXT),
    ])
    with new_session() as session:
        items = _runs(session, company_id, f)
    for r in items:
        detail = runs.get_run(company_id, r.run_id)
        for m in detail.modules:
            result.add([r.code, m.label, m.status_label, m.owner, m.approver, m.submitted_by, m.approved_by, m.total, m.valid,
                        m.invalid, m.posted, m.failed, m.amount, "؛ ".join(m.problems)])
    return result


def reconcile_report(company_id: int, f) -> ReportResult:
    from peecha.services.opening import reconcile

    result = ReportResult([
        ("فرایند", TEXT), ("ماژول", TEXT), ("حساب کنترل", TEXT), ("طرف‌حساب", TEXT), ("ماندهٔ تراز", MONEY),
        ("جمع زیرسیستم", MONEY), ("اختلاف", MONEY), ("منبع", TEXT), ("فرمول", TEXT), ("راه رفع", TEXT),
    ])
    only = _opt(f, "only", "ALL")
    with new_session() as session:
        items = _runs(session, company_id, f)
        notes = []
        for r in items:
            rec = reconcile.compute(session, company_id, r.run_id)
            for x in rec.rows:
                if only == "DIFF" and not x.difference:
                    continue
                result.add([r.code, x.module, x.account, x.counterparty, x.tb, x.sub, x.difference, x.source, x.formula, x.fix])
            state = "تراز" if rec.tb_balanced else f"تراز نیست (بدهکار {rec.tb_debit:,} / بستانکار {rec.tb_credit:,})"
            notes.append(f"{r.code}: تراز افتتاحیه {state}؛ ماندهٔ حساب واسط پس از ثبت "
                         f"{rec.clearing_posted if rec.gl_posted else rec.projected_clearing:,}")
    result.note = " | ".join(notes)
    return result


_ROW_STATUS_OPT = ("status", "وضعیت ردیف", (("ALL", "همه"), ("INVALID", "دارای خطا"), ("FAILED", "ثبت ناموفق"),
                                             ("VALID", "معتبر"), ("POSTED", "ثبت‌شده"), ("REVERSED", "برگشت‌خورده")))
_MODULE_OPT = ("module", "ماژول", (("ALL", "همه"),) + tuple(c.MODULE_LABELS.items()))


def rows_report(company_id: int, f) -> ReportResult:
    result = ReportResult([
        ("فرایند", TEXT), ("ماژول", TEXT), ("ردیف فایل", INT), ("کلید", TEXT), ("وضعیت", TEXT), ("مبلغ", MONEY),
        ("خطا", TEXT), ("هشدار", TEXT), ("سند ساخته‌شده", TEXT),
    ], no_total={2})
    status, module = _opt(f, "status"), _opt(f, "module")
    with new_session() as session:
        runs_by_id = {r.run_id: r for r in _runs(session, company_id, f)}
        q = select(StagedRow).where(StagedRow.run_id.in_(list(runs_by_id) or [-1])).order_by(StagedRow.run_id, StagedRow.module_code,
                                                                                           StagedRow.row_id)
        if status:
            q = q.where(StagedRow.status_code == status)
        if module:
            q = q.where(StagedRow.module_code == module)
        for row in session.scalars(q):
            target = f"{_TARGETS.get(row.target_type, row.target_type or '')} #{row.target_id}" if row.target_id else ""
            result.add([runs_by_id[row.run_id].code, c.MODULE_LABELS[row.module_code], row.source_row_no, row.row_key,
                        c.ROW_STATUS_LABELS[row.status_code], c.dec(row.amount),
                        "؛ ".join(f"{e['label']}: {e['msg']}" for e in (row.errors or [])),
                        "؛ ".join(f"{w['label']}: {w['msg']}" for w in (row.warnings or [])), target])
    return result


_TARGETS = {"STOCK_DOCUMENT": "سند انبار", "COMMERCIAL_DOCUMENT": "سند باز", "JOURNAL_ENTRY": "سند حسابداری",
            "RECEIVED_CHECK": "چک دریافتی", "ISSUED_CHECK": "چک پرداختی", "FIXED_ASSET": "دارایی", "PRODUCTION_ORDER": "دستور تولید"}
_POSTING_STATUS = {"PENDING": "در جریان", "DONE": "انجام‌شده", "FAILED": "ناموفق", "REVERSED": "برگشت‌خورده"}


def documents_report(company_id: int, f) -> ReportResult:
    from peecha.db.models.accounting import JournalEntry

    result = ReportResult([
        ("فرایند", TEXT), ("ماژول", TEXT), ("گام", TEXT), ("وضعیت", TEXT), ("سند ساخته‌شده", TEXT), ("سند حسابداری (موقت)", INT),
        ("سند حسابداری (دائم)", INT), ("ردیف‌ها", INT), ("مبلغ", MONEY), ("دفعات اجرا", INT), ("کاربر", TEXT), ("پایان", DATE),
        ("پیام", TEXT),
    ], no_total={5, 6, 9})
    with new_session() as session:
        runs_by_id = {r.run_id: r for r in _runs(session, company_id, f)}
        posts = list(session.scalars(select(Posting).where(Posting.run_id.in_(list(runs_by_id) or [-1])).order_by(Posting.posting_id)))
        jes = {j.journal_entry_id: j for j in session.scalars(select(JournalEntry).where(
            JournalEntry.journal_entry_id.in_([p.journal_entry_id for p in posts if p.journal_entry_id] or [-1])))}
        names = c.user_names(session, [p.user_id for p in posts])
        for p in posts:
            je = jes.get(p.journal_entry_id)
            target = f"{_TARGETS.get(p.target_type, p.target_type or '')} #{p.target_id}" if p.target_id else ""
            result.add([runs_by_id[p.run_id].code, c.MODULE_LABELS.get(p.module_code, p.module_code), p.step_key,
                        _POSTING_STATUS.get(p.status_code, p.status_code), target, je.temporary_no if je else None,
                        je.permanent_no if je else None, p.row_count, c.dec(p.amount), p.attempts, names.get(p.user_id, ""),
                        p.finished_at.date() if p.finished_at else None, p.message or ""])
    return result


def imports_report(company_id: int, f) -> ReportResult:
    result = ReportResult([
        ("فرایند", TEXT), ("ماژول", TEXT), ("نسخه", INT), ("نام فایل", TEXT), ("اثر فایل (SHA-256)", TEXT), ("ردیف‌ها", INT),
        ("معتبر", INT), ("دارای خطا", INT), ("ثبت‌شدهٔ نادیده", INT), ("کاربر", TEXT), ("زمان", DATE),
    ], no_total={2})
    with new_session() as session:
        runs_by_id = {r.run_id: r for r in _runs(session, company_id, f)}
        batches = list(session.scalars(select(ImportBatch).where(ImportBatch.run_id.in_(list(runs_by_id) or [-1]))
                                       .order_by(ImportBatch.batch_id)))
        names = c.user_names(session, [b.uploaded_by_user_id for b in batches])
        for b in batches:
            result.add([runs_by_id[b.run_id].code, c.MODULE_LABELS[b.module_code], b.version_no, b.file_name or "", b.file_hash or "",
                        b.row_count, b.valid_count, b.invalid_count, b.posted_skipped, names.get(b.uploaded_by_user_id, ""),
                        b.uploaded_at.date() if b.uploaded_at else None])
    return result


def events_report(company_id: int, f) -> ReportResult:
    result = ReportResult([("فرایند", TEXT), ("تاریخ", DATE), ("رویداد", TEXT), ("ماژول", TEXT), ("کاربر", TEXT), ("توضیح", TEXT)])
    with new_session() as session:
        runs_by_id = {r.run_id: r for r in _runs(session, company_id, f, include_cancelled=True)}
        events = list(session.scalars(select(OpeningEvent).where(
            OpeningEvent.run_id.in_(list(runs_by_id) or [-1]),
            func.date(OpeningEvent.created_at).between(f.date_from, f.date_to)).order_by(OpeningEvent.event_id)))
        names = c.user_names(session, [e.user_id for e in events])
        for e in events:
            result.add([runs_by_id[e.run_id].code, e.created_at.date(), c.EVENT_LABELS.get(e.event_code, e.event_code),
                        c.MODULE_LABELS.get(e.module_code, "") if e.module_code else "", names.get(e.user_id, ""), e.comment or ""])
    return result


def open_items_report(company_id: int, f) -> ReportResult:
    from peecha.db.models.accounting import DetailAccount
    from peecha.db.models.commercial import CommercialDocument, InvoiceSettlement
    from peecha.services import commercial_settlements as settlements

    result = ReportResult([
        ("نوع", TEXT), ("شماره", INT), ("طرف‌حساب", TEXT), ("شمارهٔ سیستم قبلی", TEXT), ("سررسید", DATE), ("ارز", TEXT),
        ("مبلغ اصلی", MONEY), ("تسویه‌شده", MONEY), ("مانده", MONEY), ("وضعیت", TEXT),
    ], no_total={1})
    with new_session() as session:
        docs = list(session.scalars(select(CommercialDocument).where(
            CommercialDocument.company_id == company_id,
            CommercialDocument.document_type_code.in_(tuple(settlements.OPENING_ITEM_LABELS))).order_by(CommercialDocument.document_id)))
        settled = dict(session.execute(select(InvoiceSettlement.invoice_document_id, func.sum(InvoiceSettlement.amount)).where(
            InvoiceSettlement.invoice_document_id.in_([d.document_id for d in docs] or [-1])).group_by(InvoiceSettlement.invoice_document_id)).all())
        parties = {d.detail_account_id: f"{d.code} — {d.name or ''}" for d in session.scalars(select(DetailAccount).where(
            DetailAccount.detail_account_id.in_({d.counterparty_detail_account_id for d in docs} or {-1})))}
        from peecha.db.models.core import Currency

        curs = {cur.currency_id: cur.iso_code for cur in session.scalars(select(Currency))}
        for d in docs:
            s = c.dec(settled.get(d.document_id))
            result.add([settlements.OPENING_ITEM_LABELS[d.document_type_code], d.document_no, parties.get(d.counterparty_detail_account_id, ""),
                        d.reference_no or "", d.due_date, curs.get(d.currency_id, ""), c.dec(d.total_amount), s,
                        c.dec(d.total_amount) - s if d.status_code == "POSTED" else c.ZERO,
                        "باطل" if d.status_code == "CANCELLED" else ("تسویه‌شده" if c.dec(d.total_amount) <= s else "باز")])
    return result


_ONLY_OPT = ("only", "نمایش", (("ALL", "همهٔ حساب‌های کنترل"), ("DIFF", "فقط دارای اختلاف")))

OPN_REPORTS: list[ReportDef] = [
    ReportDef("OPN_RUNS", "فرایندهای افتتاحیه و پیشرفت", runs_report, (),
              "هر فرایند با سال مالی، تاریخ مانده‌ها، شروع عملیات، وضعیت و درصد پیشرفت.", "none", _G, options=(_CANCELLED_OPT,)),
    ReportDef("OPN_MODULES", "وضعیت ماژول‌ها و مسئولان", modules_report, (),
              "هر ماژول هر فرایند: وضعیت، مسئول ورود، تأییدکننده، تعداد ردیف‌ها و موارد ناقص.", "none", _G, options=(_CANCELLED_OPT,)),
    ReportDef("OPN_RECONCILE", "تطبیق زیرسیستم‌ها با تراز افتتاحیه", reconcile_report, (),
              "ماندهٔ تراز، جمع زیرسیستم و اختلاف هر حساب کنترل (دریافتنی/پرداختنی به تفکیک طرف‌حساب) با منبع، فرمول و راه رفع.",
              "none", _G, options=(_ONLY_OPT, _CANCELLED_OPT)),
    ReportDef("OPN_ROWS", "ردیف‌های واردشده و خطاها", rows_report, (),
              "هر ردیف ورودی با وضعیت، خطا و هشدار به تفکیک ستون، و سند ساخته‌شده از آن.", "none", _G,
              options=(_ROW_STATUS_OPT, _MODULE_OPT, _CANCELLED_OPT)),
    ReportDef("OPN_DOCUMENTS", "اسناد ساخته‌شده و گام‌های ثبت", documents_report, (),
              "هر گام ثبت قطعی: سند ساخته‌شده، شمارهٔ سند حسابداری موقت/دائم، دفعات اجرا و پیام خطا.", "none", _G,
              options=(_CANCELLED_OPT,)),
    ReportDef("OPN_IMPORTS", "نسخه‌های بارگذاری فایل", imports_report, (),
              "نام فایل، اثر SHA-256، کاربر، زمان و نتیجهٔ هر بارگذاری.", "none", _G, options=(_CANCELLED_OPT,)),
    ReportDef("OPN_EVENTS", "تاریخچه و ردپای افتتاحیه", events_report, (),
              "همهٔ رویدادها: ایجاد، ورود، ارسال، تأیید، رد، ثبت، اختلاف با مجوز، قفل و اصلاح.", "range", _G),
    ReportDef("OPN_OPEN_ITEMS", "اسناد باز افتتاحیهٔ دریافتنی و پرداختنی", open_items_report, (),
              "ریز اسناد منتقل‌شده با مبلغ اصلی، تسویه‌شده (پیش و پس از برش) و مانده.", "none", _G),
]
