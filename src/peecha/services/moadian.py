"""R348: سامانهٔ مودیان — ساخت صورتحساب الکترونیکی از فاکتور فروش و برگشت از فروش ثبت‌شده، شمارهٔ مالیاتی، ارسال،
استعلام وضعیت و ابطال.

کدهای سامانه: نوع صورتحساب inty (۱ با مشخصات خریدار، ۲ بدون آن)، الگو inp=1 (فروش)، موضوع ins (۱ اصلی، ۳ ابطالی،
۴ برگشت از فروش)، نوع خریدار tob (۱ حقیقی، ۲ حقوقی)، روش تسویه setm (۱ نقد، ۲ نسیه). مبالغ به ریال و عدد صحیح‌اند.
اصلاحی (ins=2) در این نسخه نیست: ابطال و صدور دوباره."""

from __future__ import annotations

import copy
import datetime
import decimal
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha import numerals
from peecha.db.base import new_session
from peecha.db.models.accounting import CustomerDetail, DetailAccount
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine, MoadianInvoice, MoadianSettings, PartyAddress
from peecha.db.models.core import Company, Currency
from peecha.db.models.inventory import Item, Uom
from peecha.services import ecommerce_credentials, moadian_protocol as protocol

SUBJECT_MAIN, SUBJECT_CANCEL, SUBJECT_RETURN = 1, 3, 4
SUBJECT_LABELS = {1: "اصلی", 3: "ابطالی", 4: "برگشت از فروش"}
STATUS_LABELS = {"PREPARED": "آمادهٔ ارسال", "SENT": "ارسال‌شده، در انتظار نتیجه", "SUCCESS": "پذیرفته‌شده", "FAILED": "ردشده"}
_SUBJECT_BY_TYPE = {"SALES_INVOICE": SUBJECT_MAIN, "SALES_RETURN": SUBJECT_RETURN}
_ACTIVE = ("PREPARED", "SENT", "SUCCESS")
_ONE = decimal.Decimal(1)


@dataclass
class SettingsRow:
    memory_id: str
    seller_tin: str
    branch_code: str
    api_url: str
    has_credentials: bool
    last_serial: int


def get_settings(company_id: int) -> SettingsRow:
    with new_session() as session:
        row = session.get(MoadianSettings, company_id)
        if row is None:
            return SettingsRow("", "", "", protocol.DEFAULT_API_URL, False, 0)
        return SettingsRow(row.memory_id or "", row.seller_tin or "", row.branch_code or "",
                           row.api_url or protocol.DEFAULT_API_URL, bool(row.credentials_encrypted), row.last_serial)


def save_settings(company_id: int, memory_id: str, seller_tin: str, branch_code: str = "", api_url: str = "",
                  private_key_pem: str | None = None, certificate_pem: str | None = None) -> None:
    """کلید و گواهی فقط وقتی هر دو داده شوند جایگزین می‌شوند (رمزشده ذخیره می‌شوند)."""
    memory_id = memory_id.strip().upper()
    seller_tin = numerals.to_ascii_digits(seller_tin.strip())
    branch_code = numerals.to_ascii_digits((branch_code or "").strip())
    api_url = (api_url or "").strip() or protocol.DEFAULT_API_URL
    if memory_id and (len(memory_id) != 6 or not memory_id.isalnum() or not memory_id.isascii()):
        raise ValueError("شناسهٔ یکتای حافظهٔ مالیاتی باید ۶ حرف یا رقم لاتین باشد.")
    if seller_tin and (not seller_tin.isdigit() or not 10 <= len(seller_tin) <= 14):
        raise ValueError("شمارهٔ اقتصادی فروشنده باید ۱۰ تا ۱۴ رقم باشد.")
    if branch_code and not branch_code.isdigit():
        raise ValueError("کد شعبه فقط باید رقم باشد.")
    if not api_url.startswith("https://"):
        raise ValueError("آدرس سامانهٔ مودیان باید با https:// شروع شود.")
    if bool(private_key_pem) != bool(certificate_pem):
        raise ValueError("کلید خصوصی و گواهی را با هم وارد کنید.")
    blob = None
    if private_key_pem:
        protocol.Credentials(private_key_pem, certificate_pem).load()
        blob = ecommerce_credentials.encrypt_credentials({"private_key": private_key_pem, "certificate": certificate_pem})
    with new_session() as session:
        row = session.get(MoadianSettings, company_id) or MoadianSettings(company_id=company_id, last_serial=0)
        row.memory_id, row.seller_tin, row.branch_code, row.api_url = memory_id or None, seller_tin or None, branch_code or None, api_url
        if blob is not None:
            row.credentials_encrypted = blob
        session.add(row)
        session.commit()


def _credentials(row: MoadianSettings) -> protocol.Credentials:
    data = ecommerce_credentials.decrypt_credentials(row.credentials_encrypted)
    if not data:
        raise ValueError("کلید خصوصی و گواهی امضا در تنظیمات مودیان وارد نشده است.")
    return protocol.Credentials(data["private_key"], data["certificate"])


def _rial(session, company_id: int) -> decimal.Decimal | None:
    """ضریب تبدیل ارز پایه به ریال (تومان ×۱۰)؛ None یعنی ارز پایه ریالی نیست."""
    code = session.scalar(select(Currency.iso_code).join(Company, Company.base_currency_id == Currency.currency_id)
                          .where(Company.company_id == company_id))
    return {"IRR": _ONE, "IRT": decimal.Decimal(10)}.get(code)


def _int(value: decimal.Decimal) -> int:
    return int(decimal.Decimal(value).quantize(_ONE, rounding=decimal.ROUND_HALF_UP))


def _num(value: decimal.Decimal):
    value = decimal.Decimal(value).normalize()
    return int(value) if value == value.to_integral_value() else float(value)


def _buyer(session, doc: CommercialDocument) -> dict:
    customer = session.get(CustomerDetail, doc.counterparty_detail_account_id)
    economic = numerals.to_ascii_digits((customer.economic_code or "").strip()) if customer else ""
    national = numerals.to_ascii_digits((customer.national_id or "").strip()) if customer else ""
    postal = session.scalar(select(PartyAddress.postal_code).where(
        PartyAddress.party_detail_account_id == doc.counterparty_detail_account_id, PartyAddress.postal_code.is_not(None))
        .order_by(PartyAddress.is_default.desc(), PartyAddress.address_id))
    if not (economic or national):
        return {"inty": 2, "tob": None, "tinb": None, "bid": None, "bpc": None}
    legal = (customer.person_type_code == "LEGAL") if customer.person_type_code else len(national) == 11
    return {"inty": 1, "tob": 2 if legal else 1, "tinb": economic or national, "bid": national or None,
            "bpc": numerals.to_ascii_digits(postal) if postal else None}


def build_payload(document_id: int, company_id: int) -> tuple[dict, list[str]]:
    """بدنهٔ صورتحساب بدون شمارهٔ مالیاتی، و فهرست ایرادهایی که مانع ارسال‌اند."""
    problems: list[str] = []
    with new_session() as session:
        doc = session.get(CommercialDocument, document_id)
        if doc is None or doc.company_id != company_id:
            raise ValueError("سند یافت نشد.")
        settings = session.get(MoadianSettings, company_id)
        if settings is None or not settings.memory_id:
            problems.append("شناسهٔ یکتای حافظهٔ مالیاتی در تنظیمات مودیان وارد نشده است.")
        if settings is None or not settings.seller_tin:
            problems.append("شمارهٔ اقتصادی فروشنده در تنظیمات مودیان وارد نشده است.")
        if doc.document_type_code not in _SUBJECT_BY_TYPE:
            problems.append("فقط فاکتور فروش و برگشت از فروش به سامانهٔ مودیان فرستاده می‌شود.")
        if doc.status_code != "POSTED":
            problems.append("سند هنوز ثبت قطعی نشده است.")
        factor = _rial(session, company_id)
        if factor is None:
            problems.append("ارز پایهٔ شرکت ریال یا تومان نیست.")
            factor = _ONE
        rate = decimal.Decimal(doc.exchange_rate or 1) * factor
        if doc.shipping_amount:
            problems.append("هزینهٔ حمل جدا از ردیف‌ها در سامانه پذیرفته نیست؛ آن را به صورت ردیف خدمت ثبت کنید.")
        lines = session.scalars(select(CommercialDocumentLine).where(CommercialDocumentLine.document_id == document_id)
                                .order_by(CommercialDocumentLine.line_no)).all()
        if decimal.Decimal(doc.discount_amount or 0) - sum((l.discount_amount or 0 for l in lines), decimal.Decimal(0)) > _ONE:
            problems.append("تخفیف کل سند باید روی ردیف‌ها پخش شده باشد.")
        body = []
        for line in lines:
            item = session.get(Item, line.item_id)
            name = session.scalar(select(DetailAccount.name).where(DetailAccount.detail_account_id == item.item_detail_account_id))
            uom = session.get(Uom, line.uom_id)
            if not item.moadian_stuff_id:
                problems.append(f"شناسهٔ کالا/خدمت مودیان برای «{name}» وارد نشده است.")
            if not uom.moadian_unit_code:
                problems.append(f"کد واحد سنجش مودیان برای واحد «{uom.name}» وارد نشده است.")
            quantity = decimal.Decimal(line.quantity)
            fee = (decimal.Decimal(line.unit_price) * rate).quantize(decimal.Decimal("0.0001")).normalize()
            prdis = _int(quantity * fee)
            dis = _int(decimal.Decimal(line.discount_amount or 0) * rate)
            vra = decimal.Decimal(line.tax_percent or 0)
            adis = prdis - dis
            vam = _int(adis * vra / 100)
            body.append({"sstid": item.moadian_stuff_id, "sstt": name, "am": _num(quantity), "mu": uom.moadian_unit_code,
                         "fee": _num(fee), "prdis": prdis, "dis": dis, "adis": adis, "vra": _num(vra), "vam": vam,
                         "tsstam": adis + vam})
        if not body:
            problems.append("سند ردیفی ندارد.")
        buyer = _buyer(session, doc)
        header = {
            "indatim": protocol.invoice_timestamp(doc.document_date), "indati2m": protocol.invoice_timestamp(doc.document_date),
            "inty": buyer["inty"], "inp": 1, "ins": _SUBJECT_BY_TYPE.get(doc.document_type_code, SUBJECT_MAIN),
            "tins": settings.seller_tin if settings else None, "tob": buyer["tob"], "bid": buyer["bid"],
            "tinb": buyer["tinb"], "sbc": settings.branch_code if settings else None, "bpc": buyer["bpc"],
            "tprdis": sum(b["prdis"] for b in body), "tdis": sum(b["dis"] for b in body), "tadis": sum(b["adis"] for b in body),
            "tvam": sum(b["vam"] for b in body), "todam": 0, "tbill": sum(b["tsstam"] for b in body),
            "setm": 1 if doc.pos_session_id else 2, "cap": None, "insp": None,
        }
        if doc.document_type_code == "SALES_RETURN":
            original = _accepted(session, doc.source_document_id)
            if original is None:
                problems.append("صورتحساب فروش اصلی این برگشت هنوز در سامانه پذیرفته نشده است.")
            header["irtaxid"] = original.tax_id if original else None
        return {"header": header, "body": body, "payments": []}, problems


def _accepted(session, document_id: int | None) -> MoadianInvoice | None:
    if document_id is None:
        return None
    return session.scalar(select(MoadianInvoice).where(
        MoadianInvoice.document_id == document_id, MoadianInvoice.subject_code == SUBJECT_MAIN,
        MoadianInvoice.status == "SUCCESS").order_by(MoadianInvoice.moadian_invoice_id.desc()))


def _next_serial(session, company_id: int) -> tuple[MoadianSettings, int]:
    settings = session.scalar(select(MoadianSettings).where(MoadianSettings.company_id == company_id).with_for_update())
    settings.last_serial += 1
    return settings, settings.last_serial


def _store(session, company_id: int, document_id: int, subject: int, payload: dict, user_id: int | None,
           related: str | None = None) -> MoadianInvoice:
    settings, serial = _next_serial(session, company_id)
    payload = copy.deepcopy(payload)
    header = payload["header"]
    header["taxid"] = protocol.tax_id(settings.memory_id, header["indatim"], serial)
    header["inno"] = header["taxid"][11:21]
    header["ins"] = subject
    if related:
        header["irtaxid"] = related
    row = MoadianInvoice(company_id=company_id, document_id=document_id, subject_code=subject, serial=serial,
                         tax_id=header["taxid"], related_tax_id=header.get("irtaxid"), payload=payload, status="PREPARED",
                         created_by_user_id=user_id)
    session.add(row)
    session.flush()
    return row


def prepare(document_id: int, company_id: int, user_id: int | None = None) -> str:
    """صورتحساب اصلی یا برگشت از فروش را آمادهٔ ارسال می‌کند و شمارهٔ مالیاتی را برمی‌گرداند."""
    payload, problems = build_payload(document_id, company_id)
    if problems:
        raise ValueError("\n".join(problems))
    subject = payload["header"]["ins"]
    with new_session() as session:
        if session.scalar(select(MoadianInvoice.moadian_invoice_id).where(
                MoadianInvoice.document_id == document_id, MoadianInvoice.subject_code == subject,
                MoadianInvoice.status.in_(_ACTIVE))):
            raise ValueError("صورتحساب این سند قبلاً ساخته یا ارسال شده است.")
        row = _store(session, company_id, document_id, subject, payload, user_id)
        session.commit()
        return row.tax_id


def prepare_cancel(document_id: int, company_id: int, user_id: int | None = None) -> str:
    """ابطال صورتحساب پذیرفته‌شده: همان صورتحساب با موضوع ابطالی و ارجاع به شمارهٔ مالیاتی اصلی."""
    with new_session() as session:
        original = _accepted(session, document_id)
        if original is None or original.company_id != company_id:
            raise ValueError("برای این سند صورتحساب پذیرفته‌شده‌ای نیست که باطل شود.")
        if session.scalar(select(MoadianInvoice.moadian_invoice_id).where(
                MoadianInvoice.related_tax_id == original.tax_id, MoadianInvoice.subject_code == SUBJECT_CANCEL,
                MoadianInvoice.status.in_(_ACTIVE))):
            raise ValueError("ابطال این صورتحساب قبلاً ساخته یا ارسال شده است.")
        row = _store(session, company_id, document_id, SUBJECT_CANCEL, original.payload, user_id, original.tax_id)
        session.commit()
        return row.tax_id


def _client(session, company_id: int, transport=None) -> protocol.Client:
    settings = session.get(MoadianSettings, company_id)
    if settings is None or not settings.memory_id:
        raise ValueError("تنظیمات مودیان کامل نیست.")
    return protocol.Client(settings.api_url or protocol.DEFAULT_API_URL, settings.memory_id, _credentials(settings), transport)


def send_prepared(company_id: int, transport=None) -> int:
    """همهٔ صورتحساب‌های آمادهٔ ارسال را می‌فرستد؛ تعداد ارسال‌شده را برمی‌گرداند."""
    with new_session() as session:
        rows = session.scalars(select(MoadianInvoice).where(
            MoadianInvoice.company_id == company_id, MoadianInvoice.status == "PREPARED")
            .order_by(MoadianInvoice.moadian_invoice_id)).all()
        if not rows:
            return 0
        client = _client(session, company_id, transport)
        now = datetime.datetime.now(datetime.timezone.utc)
        for start in range(0, len(rows), 50):
            chunk = rows[start:start + 50]
            try:
                results = client.send([r.payload for r in chunk])
            except protocol.MoadianError as exc:
                session.commit()
                raise ValueError(str(exc)) from exc
            for row, result in zip(chunk, results):
                row.uid, row.reference_number, row.sent_at = result.get("uid"), result.get("referenceNumber"), now
                if result.get("errorCode") or not result.get("referenceNumber"):
                    row.status, row.errors = "FAILED", [{"code": result.get("errorCode"), "message": result.get("errorDetail")}]
                else:
                    row.status = "SENT"
        session.commit()
        return sum(1 for r in rows if r.status == "SENT")


def check_sent(company_id: int, transport=None) -> int:
    """نتیجهٔ صورتحساب‌های ارسال‌شده را از سامانه می‌پرسد؛ تعداد تعیین‌تکلیف‌شده را برمی‌گرداند."""
    with new_session() as session:
        rows = session.scalars(select(MoadianInvoice).where(
            MoadianInvoice.company_id == company_id, MoadianInvoice.status == "SENT")).all()
        if not rows:
            return 0
        client = _client(session, company_id, transport)
        by_uid = {r.uid: r for r in rows}
        try:
            results = client.inquiry_by_uid(list(by_uid))
        except protocol.MoadianError as exc:
            raise ValueError(str(exc)) from exc
        now, settled = datetime.datetime.now(datetime.timezone.utc), 0
        for result in results:
            row = by_uid.get(result.get("uid"))
            if row is None:
                continue
            row.checked_at = now
            status = result.get("status")
            data = result.get("data") or {}
            if status in ("SUCCESS", "FAILED"):
                row.status = status
                row.errors = (data.get("error") or []) + (data.get("warning") or []) or None
                settled += 1
        session.commit()
        return settled


@dataclass
class InvoiceRow:
    document_id: int
    document_type_code: str
    document_no: int
    document_date: datetime.date
    customer: str
    total: decimal.Decimal
    moadian_invoice_id: int | None = None
    subject_code: int | None = None
    tax_id: str = ""
    status: str = ""
    errors: list = field(default_factory=list)


def list_documents(company_id: int, date_from: datetime.date, date_to: datetime.date) -> list[InvoiceRow]:
    """فاکتورهای فروش و برگشت‌های ثبت‌شدهٔ بازه با آخرین وضعیت مودیان هر کدام."""
    with new_session() as session:
        docs = session.execute(
            select(CommercialDocument, DetailAccount.name)
            .join(DetailAccount, DetailAccount.detail_account_id == CommercialDocument.counterparty_detail_account_id)
            .where(CommercialDocument.company_id == company_id, CommercialDocument.status_code == "POSTED",
                   CommercialDocument.document_type_code.in_(tuple(_SUBJECT_BY_TYPE)),
                   CommercialDocument.document_date.between(date_from, date_to))
            .order_by(CommercialDocument.document_date, CommercialDocument.document_no)).all()
        latest: dict[int, MoadianInvoice] = {}
        if docs:
            for row in session.scalars(select(MoadianInvoice).where(
                    MoadianInvoice.document_id.in_([d.document_id for d, _ in docs]))
                    .order_by(MoadianInvoice.moadian_invoice_id)):
                latest[row.document_id] = row
        out = []
        for doc, name in docs:
            row = latest.get(doc.document_id)
            item = InvoiceRow(doc.document_id, doc.document_type_code, doc.document_no, doc.document_date, name or "",
                              doc.total_amount)
            if row is not None:
                item.moadian_invoice_id, item.subject_code, item.tax_id, item.status = (
                    row.moadian_invoice_id, row.subject_code, row.tax_id, row.status)
                item.errors = list(row.errors or [])
            out.append(item)
        return out


def get_payload(moadian_invoice_id: int, company_id: int) -> dict:
    with new_session() as session:
        row = session.get(MoadianInvoice, moadian_invoice_id)
        if row is None or row.company_id != company_id:
            raise ValueError("صورتحساب یافت نشد.")
        return copy.deepcopy(row.payload)
