"""R362: گواهی آنالیز (COA) از بازرسی تأییدشده.

- فقط بازرسی تأییدشده با نتیجهٔ «پذیرفته» یا «پذیرش بخشی» که دست‌کم یک نتیجهٔ پارامتر دارد و همهٔ پارامترهای الزامی‌اش
  در حد مجاز است گواهی می‌گیرد.
- مشخصات کالا، بچ، تاریخ‌ها و نتایج پارامترها هنگام صدور ثابت ذخیره می‌شود؛ تغییر بعدی بازرسی گواهی صادرشده را عوض نمی‌کند.
- گواهی شماره‌گذاری می‌شود، می‌تواند به مشتری و سند فروش همان کالا وصل شود و فقط با ذکر دلیل لغو می‌شود (حذف نمی‌شود).
"""

from __future__ import annotations

import datetime
import decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine
from peecha.db.models.inventory import Batch, QcInspection, StockDocumentLine
from peecha.db.models.quality import Certificate, InspectionResult
from peecha.services.qms import queries

STATUSES = {"ISSUED": "صادرشده", "REVOKED": "لغوشده"}
_SALES_TYPES = ("SALES_ORDER", "SALES_INVOICE")


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, decimal.Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return str(value)


def _batch(session, q: QcInspection) -> Batch | None:
    batch_id = q.batch_id
    if batch_id is None and q.stock_document_line_id:
        ln = session.get(StockDocumentLine, q.stock_document_line_id)
        batch_id = ln.batch_id if ln else None
    return session.get(Batch, batch_id) if batch_id else None


def _problems(session, q: QcInspection | None, company_id: int) -> str | None:
    if q is None or q.company_id != company_id:
        return "بازرسی نامعتبر است."
    if q.status_code != "APPROVED":
        return "گواهی فقط برای بازرسی تأییدشده صادر می‌شود."
    if q.result_code not in ("APPROVED", "PARTIAL"):
        return "بازرسی مردود یا بی‌تصمیم گواهی آنالیز نمی‌گیرد."
    results = list(session.scalars(select(InspectionResult).where(InspectionResult.qc_inspection_id == q.qc_inspection_id)))
    if not results:
        return "این بازرسی نتیجهٔ پارامتر ندارد؛ گواهی آنالیز بدون نتیجه صادر نمی‌شود."
    bad = next((r for r in results if r.is_mandatory and r.is_conforming is False), None)
    if bad is not None:
        return f"نتیجهٔ «{bad.parameter_name}» خارج از حد است؛ گواهی صادر نمی‌شود."
    return None


def eligible_inspections(company_id: int, limit: int = 300) -> list[SimpleNamespace]:
    with new_session() as session:
        rows = list(session.scalars(select(QcInspection).where(
            QcInspection.company_id == company_id, QcInspection.status_code == "APPROVED",
            QcInspection.result_code.in_(("APPROVED", "PARTIAL"))).order_by(QcInspection.qc_inspection_id.desc()).limit(limit)))
        ok = [q for q in rows if _problems(session, q, company_id) is None]
        batches = {q.qc_inspection_id: _batch(session, q) for q in ok}
        issued = dict(session.execute(select(Certificate.qc_inspection_id, func.count()).where(
            Certificate.qc_inspection_id.in_([q.qc_inspection_id for q in ok] or [0]), Certificate.status_code == "ISSUED")
            .group_by(Certificate.qc_inspection_id)).all())
    heads = {r.inspection_id: r for r in queries.list_inspections(company_id, status="APPROVED", limit=limit)}
    return [SimpleNamespace(inspection_id=q.qc_inspection_id, item_id=heads[q.qc_inspection_id].item_id,
                            item_label=heads[q.qc_inspection_id].item_label, stage_label=heads[q.qc_inspection_id].stage_label,
                            result_label=heads[q.qc_inspection_id].result_label,
                            batch_no=batches[q.qc_inspection_id].batch_no if batches[q.qc_inspection_id] else "",
                            approved_at=q.approved_at, certificates=issued.get(q.qc_inspection_id, 0))
            for q in ok if q.qc_inspection_id in heads]


def issue(company_id: int, user_id: int, qc_inspection_id: int, *, customer_id: int | None = None,
          sales_document_id: int | None = None, issue_date: datetime.date | None = None, notes: str | None = None) -> int:
    detail = queries.inspection_detail(company_id, qc_inspection_id)
    head = detail.header
    if head.item_id is None:
        raise ValueError("کالای این بازرسی معلوم نیست.")
    with new_session() as session:
        q = session.get(QcInspection, qc_inspection_id)
        problem = _problems(session, q, company_id)
        if problem:
            raise ValueError(problem)
        if sales_document_id:
            doc = session.get(CommercialDocument, sales_document_id)
            if doc is None or doc.company_id != company_id or doc.document_type_code not in _SALES_TYPES:
                raise ValueError("سند فروش نامعتبر است.")
            if not session.scalar(select(CommercialDocumentLine.line_id).where(
                    CommercialDocumentLine.document_id == sales_document_id, CommercialDocumentLine.item_id == head.item_id).limit(1)):
                raise ValueError("این کالا در سند فروش انتخاب‌شده نیست.")
            if customer_id and customer_id != doc.counterparty_detail_account_id:
                raise ValueError("مشتری با طرف حساب سند فروش یکی نیست.")
            customer_id = doc.counterparty_detail_account_id
        batch = _batch(session, q)
        customer = session.get(DetailAccount, customer_id) if customer_id else None
        snapshot = {
            "item": head.item_label, "batch_no": batch.batch_no if batch else None,
            "manufacture_date": _text(batch.manufacture_date) if batch else None,
            "expiry_date": _text(batch.expiry_date) if batch else None,
            "inspection_id": qc_inspection_id, "stage": head.stage_label, "plan": head.plan_label,
            "inspected_at": _text(head.inspected_at), "approved_at": _text(head.approved_at), "inspector": head.inspector,
            "approver": head.approver, "lot": _text(head.lot), "accepted": _text(head.accepted),
            "customer": customer.name if customer else None,
            "results": [{"sample_no": r.sample_no, "name": r.name, "unit": r.unit, "min": _text(r.min_value), "max": _text(r.max_value),
                         "target": _text(r.target_value), "value": _text(r.value), "conforming": r.conforming}
                        for r in detail.results],
        }
        session.execute(select(Certificate.certificate_id).where(Certificate.company_id == company_id).with_for_update())
        number = (session.scalar(select(func.max(Certificate.certificate_no)).where(Certificate.company_id == company_id)) or 0) + 1
        row = Certificate(company_id=company_id, certificate_no=number, qc_inspection_id=qc_inspection_id, item_id=head.item_id,
                          batch_no=batch.batch_no if batch else None, customer_detail_account_id=customer_id,
                          sales_document_id=sales_document_id, issue_date=issue_date or datetime.date.today(), snapshot=snapshot,
                          notes=(notes or "").strip() or None, issued_by_user_id=user_id)
        session.add(row)
        session.commit()
        return row.certificate_id


def revoke(company_id: int, user_id: int, certificate_id: int, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("دلیل لغو گواهی را بنویسید.")
    with new_session() as session:
        row = session.get(Certificate, certificate_id)
        if row is None or row.company_id != company_id:
            raise ValueError("گواهی نامعتبر است.")
        if row.status_code == "REVOKED":
            raise ValueError("این گواهی قبلاً لغو شده است.")
        row.status_code, row.revoke_reason = "REVOKED", reason.strip()
        row.revoked_by_user_id, row.revoked_at = user_id, datetime.datetime.now(datetime.timezone.utc)
        session.commit()


def _view(row: Certificate, doc_no: int | None) -> SimpleNamespace:
    s = row.snapshot or {}
    return SimpleNamespace(certificate_id=row.certificate_id, certificate_no=row.certificate_no, qc_inspection_id=row.qc_inspection_id,
                           item_id=row.item_id, item_label=s.get("item", ""), batch_no=row.batch_no or "", issue_date=row.issue_date,
                           customer=s.get("customer") or "", sales_document_id=row.sales_document_id, sales_document_no=doc_no,
                           status_code=row.status_code, status_label=STATUSES[row.status_code], revoke_reason=row.revoke_reason or "",
                           notes=row.notes or "", snapshot=s)


def list_certificates(company_id: int, item_id: int | None = None, status: str | None = None) -> list[SimpleNamespace]:
    with new_session() as session:
        q = select(Certificate, CommercialDocument.document_no).outerjoin(
            CommercialDocument, CommercialDocument.document_id == Certificate.sales_document_id).where(Certificate.company_id == company_id)
        if item_id:
            q = q.where(Certificate.item_id == item_id)
        if status:
            q = q.where(Certificate.status_code == status)
        return [_view(row, no) for row, no in session.execute(q.order_by(Certificate.certificate_no.desc()))]


def get_certificate(company_id: int, certificate_id: int) -> SimpleNamespace:
    with new_session() as session:
        row = session.get(Certificate, certificate_id)
        if row is None or row.company_id != company_id:
            raise ValueError("گواهی نامعتبر است.")
        doc = session.get(CommercialDocument, row.sales_document_id) if row.sales_document_id else None
        return _view(row, doc.document_no if doc else None)


def print_table(cert: SimpleNamespace) -> tuple[str, list[str], list[list], list[tuple[str, str]]]:
    """عنوان، سرستون‌ها، ردیف نتایج و مشخصات سربرگ برای چاپ یا Excel (تاریخ‌ها رشتهٔ ISO از snapshot)."""
    from peecha import numerals

    s = cert.snapshot
    jdate = lambda v: numerals.format_jalali_date(datetime.date.fromisoformat(v[:10])) if v else ""  # noqa: E731
    headers = ["پارامتر", "واحد", "حداقل", "حداکثر", "هدف", "نتیجه", "وضعیت"]
    rows = [[r["name"] + (f" (نمونهٔ {r['sample_no']})" if r.get("sample_no", 1) != 1 else ""), r.get("unit") or "",
             r.get("min") or "", r.get("max") or "", r.get("target") or "", r.get("value") or "",
             "منطبق" if r.get("conforming") else ("نامنطبق" if r.get("conforming") is False else "—")] for r in s.get("results", [])]
    head = [("کالا", s.get("item", "")), ("شمارهٔ بچ", s.get("batch_no") or "—"), ("تاریخ تولید", jdate(s.get("manufacture_date"))),
            ("تاریخ انقضا", jdate(s.get("expiry_date"))), ("تاریخ بازرسی", jdate(s.get("inspected_at"))),
            ("تأییدکننده", s.get("approver") or ""), ("مشتری", s.get("customer") or "—")]
    if cert.status_code == "REVOKED":
        head.append(("وضعیت", f"لغوشده: {cert.revoke_reason}"))
    title = f"گواهی آنالیز شمارهٔ {numerals.to_persian_digits(str(cert.certificate_no))}"
    return title, headers, rows, [(k, v) for k, v in head if v]
