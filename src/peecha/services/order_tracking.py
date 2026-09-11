"""مدیریتِ سفارشات — طبقِ درخواستِ صریح: هر سفارش دقیقاً یک تفصیلیِ یک
گروهِ تفصیلیِ ازپیش‌تعیین‌شده («سفارشاتِ در راه») است. پرداخت‌هایِ خودِ
سفارش این‌جا دوباره ذخیره نمی‌شوند -- همان فرمِ دریافت/پرداختِ
خزانه‌داری (با هر روش/ارزی که دارد) استفاده می‌شود و تاریخچه با
پرس‌وجویِ مستقیمِ سندهایِ حسابداریِ همان تفصیلی به‌دست می‌آید؛ سندِ
حسابداریِ هر پرداخت هم دقیقاً همان‌جا (نه این‌جا) صادر می‌شود.

پیش‌نیازِ خارج از این ماژول: برایِ اینکه دکمهٔ «افزودنِ پرداخت» بتواند
تفصیلیِ سفارش را در فرمِ دریافت/پرداخت پیشنهاد بدهد، باید یک نگاشتِ
طرفِ‌حساب (treasury_counterparty_settings) برایِ همان گروهِ تفصیلی از
پیش تنظیم شده باشد -- این ماژول آن نگاشت را نمی‌سازد، فقط بودنش را
بررسی می‌کند."""

from __future__ import annotations

import datetime
import decimal
import hashlib
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from peecha.config import SETTINGS_DIR
from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount, JournalEntry, JournalEntryLine, JournalEntryLineDetail
from peecha.db.models.commercial import OrderPaymentTitle, OrderTracking, OrderTrackingSetting
from peecha.db.models.core import Company
from peecha.db.models.documents import Attachment
from peecha.db.models.security import Form
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import roles as roles_service

_LOCAL_ATTACHMENTS_DIR = SETTINGS_DIR / "attachments"


# ---------------------------------------------------------------------
# تنظیمِ گروهِ تفصیلیِ «سفارشاتِ در راه»
# ---------------------------------------------------------------------
def get_dimension_type_id(company_id: int) -> int | None:
    with new_session() as session:
        row = session.get(OrderTrackingSetting, company_id)
        return row.dimension_type_id if row is not None else None


def set_dimension_type_id(company_id: int, dimension_type_id: int) -> None:
    with new_session() as session:
        row = session.get(OrderTrackingSetting, company_id)
        if row is None:
            session.add(OrderTrackingSetting(company_id=company_id, dimension_type_id=dimension_type_id))
        else:
            row.dimension_type_id = dimension_type_id
        session.commit()


def get_attachments_dir_setting(company_id: int) -> str | None:
    with new_session() as session:
        row = session.get(OrderTrackingSetting, company_id)
        return row.attachments_dir if row is not None else None


def set_attachments_dir_setting(company_id: int, path: str | None) -> None:
    """طبقِ درخواستِ صریح («امکانِ دیدنِ عکس برایِ همه‌یِ کاربرانِ شبکه»):
    یک مسیرِ اشتراکیِ شبکه‌ای (مثلاً \\\\SERVER\\Share\\PeechaAttachments یا
    یک درایوِ نگاشته‌شده که رویِ همهٔ کامپیوترها به یک پوشه اشاره کند) --
    چون همین یک ردیف در دیتابیس ذخیره می‌شود، همهٔ کاربرانِ متصل به همان
    شرکت همین یک مسیر را می‌بینند. اگر خالی بماند، رفتارِ قبلی (پوشهٔ
    محلیِ تنظیماتِ همان کامپیوتر -- فقط رویِ همان یک دستگاه قابلِ‌دیدن)
    ادامه می‌یابد."""
    path = (path or "").strip() or None
    with new_session() as session:
        row = session.get(OrderTrackingSetting, company_id)
        if row is None:
            raise ValueError("ابتدا باید گروهِ تفصیلیِ «سفارشاتِ در راه» را تنظیم کنید.")
        row.attachments_dir = path
        session.commit()


def _attachments_dir(company_id: int) -> Path:
    configured = get_attachments_dir_setting(company_id)
    return Path(configured) if configured else _LOCAL_ATTACHMENTS_DIR


# ---------------------------------------------------------------------
# خودِ سفارش‌ها
# ---------------------------------------------------------------------
@dataclass
class OrderRow:
    order_tracking_id: int
    detail_account_id: int
    code: str
    name: str | None
    description: str | None
    status_code: str
    opened_at: datetime.datetime
    closed_at: datetime.datetime | None


def list_available_detail_accounts(company_id: int) -> list[dimensions_service.DetailAccountRow]:
    """طبقِ گزارشِ صریح («یک گروهِ تفصیلی انتخاب می‌کنم، تفصیلی‌هایِ سطحِ
    آخرش را باید نمایش بدهد»): تفصیلی‌هایِ سطحِ آخرِ همان گروهِ تنظیم‌شده
    («سفارشاتِ در راه») که هنوز به‌عنوانِ یک سفارش پیگیری نمی‌شوند -- یعنی
    آماده‌یِ انتخاب برایِ شروعِ یک سفارشِ تازه‌اند."""
    dimension_type_id = get_dimension_type_id(company_id)
    if dimension_type_id is None:
        return []
    already_tracked_ids = set()
    with new_session() as session:
        already_tracked_ids = set(
            session.scalars(select(OrderTracking.detail_account_id).where(OrderTracking.company_id == company_id))
        )
    return [
        d
        for d in dimensions_service.list_leaf_detail_accounts(company_id, dimension_type_id)
        if d.detail_account_id not in already_tracked_ids
    ]


def create_order(company_id: int, user_id: int, detail_account_id: int, description: str | None = None) -> int:
    dimension_type_id = get_dimension_type_id(company_id)
    if dimension_type_id is None:
        raise ValueError("ابتدا باید گروهِ تفصیلیِ «سفارشاتِ در راه» را در همین صفحه تنظیم کنید.")
    with new_session() as session:
        detail_account = session.get(DetailAccount, detail_account_id)
        if (
            detail_account is None
            or detail_account.company_id != company_id
            or detail_account.dimension_type_id != dimension_type_id
        ):
            raise ValueError("تفصیلیِ انتخاب‌شده متعلق به گروهِ «سفارشاتِ در راه» نیست.")
        existing = session.scalar(select(OrderTracking).where(OrderTracking.detail_account_id == detail_account_id))
        if existing is not None:
            raise ValueError("این تفصیلی قبلاً به‌عنوانِ یک سفارش پیگیری می‌شود.")
        row = OrderTracking(
            company_id=company_id, detail_account_id=detail_account_id, description=description,
            status_code="OPEN", opened_by_user_id=user_id,
        )
        session.add(row)
        session.commit()
        return row.order_tracking_id


def list_orders(company_id: int, status_code: str | None = None) -> list[OrderRow]:
    with new_session() as session:
        query = select(OrderTracking, DetailAccount).join(
            DetailAccount, DetailAccount.detail_account_id == OrderTracking.detail_account_id
        ).where(OrderTracking.company_id == company_id)
        if status_code is not None:
            query = query.where(OrderTracking.status_code == status_code)
        rows = session.execute(query.order_by(OrderTracking.opened_at.desc())).all()
        return [
            OrderRow(
                order_tracking_id=o.order_tracking_id, detail_account_id=o.detail_account_id, code=d.code,
                name=d.name, description=o.description, status_code=o.status_code, opened_at=o.opened_at,
                closed_at=o.closed_at,
            )
            for o, d in rows
        ]


def get_order(order_tracking_id: int, company_id: int) -> OrderRow | None:
    with new_session() as session:
        row = session.execute(
            select(OrderTracking, DetailAccount)
            .join(DetailAccount, DetailAccount.detail_account_id == OrderTracking.detail_account_id)
            .where(OrderTracking.order_tracking_id == order_tracking_id, OrderTracking.company_id == company_id)
        ).first()
        if row is None:
            return None
        o, d = row
        return OrderRow(
            order_tracking_id=o.order_tracking_id, detail_account_id=o.detail_account_id, code=d.code,
            name=d.name, description=o.description, status_code=o.status_code, opened_at=o.opened_at,
            closed_at=o.closed_at,
        )


def close_order(order_tracking_id: int, company_id: int, user_id: int) -> None:
    with new_session() as session:
        row = session.get(OrderTracking, order_tracking_id)
        if row is None or row.company_id != company_id:
            raise ValueError("سفارش نامعتبر است.")
        if row.status_code != "OPEN":
            raise ValueError("این سفارش قبلاً بسته شده است.")
        row.status_code = "CLOSED"
        row.closed_by_user_id = user_id
        row.closed_at = datetime.datetime.now()
        session.commit()


def reopen_order(order_tracking_id: int, company_id: int) -> None:
    with new_session() as session:
        row = session.get(OrderTracking, order_tracking_id)
        if row is None or row.company_id != company_id:
            raise ValueError("سفارش نامعتبر است.")
        if row.status_code != "CLOSED":
            raise ValueError("این سفارش بسته نیست.")
        row.status_code = "OPEN"
        row.closed_by_user_id = None
        row.closed_at = None
        session.commit()


# ---------------------------------------------------------------------
# عنوانِ پرداخت (طبقِ درخواستِ صریح: «هزینه‌یِ ترخیص»/«بهایِ اولیه‌یِ
# کالا»/... -- فهرستی که با دکمه‌یِ + همان‌جا گسترش می‌یابد)
# ---------------------------------------------------------------------
@dataclass
class PaymentTitleRow:
    payment_title_id: int
    label: str


def list_payment_titles(company_id: int) -> list[PaymentTitleRow]:
    with new_session() as session:
        rows = session.scalars(
            select(OrderPaymentTitle).where(OrderPaymentTitle.company_id == company_id).order_by(OrderPaymentTitle.label)
        )
        return [PaymentTitleRow(payment_title_id=r.payment_title_id, label=r.label) for r in rows]


def create_payment_title(company_id: int, label: str) -> int:
    label = label.strip()
    if not label:
        raise ValueError("عنوانِ پرداخت نمی‌تواند خالی باشد.")
    with new_session() as session:
        existing = session.scalar(
            select(OrderPaymentTitle).where(OrderPaymentTitle.company_id == company_id, OrderPaymentTitle.label == label)
        )
        if existing is not None:
            raise ValueError("این عنوان قبلاً تعریف شده است.")
        row = OrderPaymentTitle(company_id=company_id, label=label)
        session.add(row)
        session.commit()
        return row.payment_title_id


def update_payment_title(company_id: int, payment_title_id: int, new_label: str) -> None:
    """طبقِ گزارشِ صریح («عنوانِ پرداخت وقتی وارد می‌شود نمی‌شود ویرایش
    کرد»): عنوان‌هایِ ثبت‌شده صرفاً یک برچسبِ ساده‌اند -- ویرایش/حذفشان
    هیچ سندِ حسابداریِ قبلی را تغییر نمی‌دهد (شرحِ همان پرداخت‌ها، طبقِ
    طراحی، یک متنِ ثابتِ کپی‌شده است، نه ارجاعِ زنده به این جدول)."""
    new_label = new_label.strip()
    if not new_label:
        raise ValueError("عنوانِ پرداخت نمی‌تواند خالی باشد.")
    with new_session() as session:
        row = session.get(OrderPaymentTitle, payment_title_id)
        if row is None or row.company_id != company_id:
            raise ValueError("عنوان نامعتبر است.")
        existing = session.scalar(
            select(OrderPaymentTitle).where(
                OrderPaymentTitle.company_id == company_id,
                OrderPaymentTitle.label == new_label,
                OrderPaymentTitle.payment_title_id != payment_title_id,
            )
        )
        if existing is not None:
            raise ValueError("این عنوان قبلاً تعریف شده است.")
        row.label = new_label
        session.commit()


def delete_payment_title(company_id: int, payment_title_id: int) -> None:
    with new_session() as session:
        row = session.get(OrderPaymentTitle, payment_title_id)
        if row is None or row.company_id != company_id:
            raise ValueError("عنوان نامعتبر است.")
        session.delete(row)
        session.commit()


# ---------------------------------------------------------------------
# پرداخت‌هایِ سفارش (مشتق از سندهایِ حسابداریِ موجود -- بدونِ جدولِ واسط)
# ---------------------------------------------------------------------
@dataclass
class OrderPaymentRow:
    journal_entry_id: int
    document_date: datetime.date
    description: str
    debit: decimal.Decimal
    credit: decimal.Decimal
    # طبقِ درخواستِ صریح («اکثرا با ارزهای دیگه هم کار می‌کنن»): ارزِ خودِ
    # ردیف (نه لزوماً ارزِ پایه‌یِ شرکت) + نرخِ همان روز + مبلغِ ارزیِ خامِ
    # همان ردیف -- debit/credit بالا همیشه به ارزِ پایه‌اند (برایِ ماندهٔ
    # سفارش)، این سه فیلد برایِ نمایشِ «چه ارزی، چه نرخی، چه مبلغی» است.
    currency_id: int
    is_base_currency: bool
    exchange_rate: decimal.Decimal
    debit_fc: decimal.Decimal
    credit_fc: decimal.Decimal


def list_order_payments(company_id: int, detail_account_id: int) -> list[OrderPaymentRow]:
    with new_session() as session:
        base_currency_id = session.scalar(select(Company.base_currency_id).where(Company.company_id == company_id))
        rows = session.execute(
            select(
                JournalEntry.journal_entry_id, JournalEntry.document_date, JournalEntry.description,
                JournalEntryLine.debit_amount_base, JournalEntryLine.credit_amount_base,
                JournalEntryLine.currency_id, JournalEntryLine.exchange_rate,
                JournalEntryLine.debit_amount_fc, JournalEntryLine.credit_amount_fc,
            )
            .join(JournalEntryLine, JournalEntryLine.journal_entry_id == JournalEntry.journal_entry_id)
            .join(JournalEntryLineDetail, JournalEntryLineDetail.line_id == JournalEntryLine.line_id)
            .where(JournalEntry.company_id == company_id, JournalEntryLineDetail.detail_account_id == detail_account_id)
            .order_by(JournalEntry.document_date, JournalEntry.journal_entry_id)
        ).all()
        return [
            OrderPaymentRow(
                journal_entry_id=r[0], document_date=r[1], description=r[2] or "", debit=r[3], credit=r[4],
                currency_id=r[5], is_base_currency=(r[5] == base_currency_id), exchange_rate=r[6],
                debit_fc=r[7], credit_fc=r[8],
            )
            for r in rows
        ]


# ---------------------------------------------------------------------
# فایلِ ضمیمهٔ هر ردیفِ پرداخت (doc.attachments، source_record_id =
# journal_entry_id همان پرداخت) -- طبقِ درخواستِ صریح، هر نوع فایلی
# (عکس/PDF/...) می‌تواند ضمیمه شود، نه فقط عکس.
# ---------------------------------------------------------------------
_FORM_CODE = "order_tracking"


def _get_form_id(session, company_id: int) -> int:
    """طبقِ باگِ کشف‌شده (گزارشِ صریح: «هیچ عکسی نمی‌شود الصاق کنم» --
    که در واقع علتِ ریشه‌ایِ «فقط پرداختِ اول نمایش داده می‌شود» هم بود):
    sec.forms فقط با ensure_catalog() پر می‌شود، که تا پیش از این فقط از
    صفحه‌ی «نقش‌ها» یا کارتیبل صدا زده می‌شد -- اگر کاربر هیچ‌کدام را باز
    نکرده باشد، ردیفِ این فرم اصلاً وجود ندارد. این‌جا idempotent صدا
    زده می‌شود تا این پیش‌نیاز همیشه، بدونِ وابستگی به بازکردنِ صفحه‌ی
    دیگری، برقرار باشد."""
    roles_service.ensure_catalog()
    form = session.scalar(select(Form).where(Form.code == _FORM_CODE))
    if form is None:
        raise ValueError("فرمِ «مدیریتِ سفارشات» هنوز در فهرستِ فرم‌ها ثبت نشده است.")
    return form.form_id


def attach_file(company_id: int, journal_entry_id: int, user_id: int, file_path: str) -> int:
    """طبقِ درخواستِ صریح («عکس در دیتابیس ذخیره نشود، فقط مسیر، چون
    دیتابیس حجیم می‌شود»): فقط storage_key (مسیرِ فایل) در دیتابیس
    می‌رود؛ خودِ فایل در _attachments_dir(company_id) کپی می‌شود -- که
    اگر مدیر یک مسیرِ شبکه‌ایِ اشتراکی تنظیم کرده باشد، همان پوشه است
    (پس همهٔ کاربران به همان فایل دسترسی دارند)، وگرنه پوشهٔ محلیِ
    تنظیماتِ همین کامپیوتر (رفتارِ پیش‌فرض/قدیمی)."""
    source = Path(file_path)
    if not source.is_file():
        raise ValueError("فایل یافت نشد.")
    target_dir = _attachments_dir(company_id)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"پوشهٔ ضمائم («{target_dir}») در دسترس نیست: {exc}") from exc
    content = source.read_bytes()
    digest = hashlib.sha256(content).digest()
    extension = source.suffix.lstrip(".")
    storage_name = f"{uuid.uuid4().hex}.{extension}" if extension else uuid.uuid4().hex
    destination = target_dir / storage_name
    shutil.copyfile(source, destination)
    with new_session() as session:
        form_id = _get_form_id(session, company_id)
        row = Attachment(
            company_id=company_id, form_id=form_id, source_record_id=journal_entry_id,
            file_name=source.name, file_extension=extension, file_size_bytes=len(content),
            storage_key=str(destination), content_sha256=digest, uploaded_by_user_id=user_id,
        )
        session.add(row)
        session.commit()
        return row.attachment_id


def list_files(company_id: int, journal_entry_id: int) -> list[Attachment]:
    with new_session() as session:
        form_id = _get_form_id(session, company_id)
        return list(
            session.scalars(
                select(Attachment).where(
                    Attachment.form_id == form_id, Attachment.source_record_id == journal_entry_id,
                    Attachment.is_deleted.is_(False),
                ).order_by(Attachment.uploaded_at)
            )
        )


def delete_file(attachment_id: int, company_id: int, user_id: int) -> None:
    with new_session() as session:
        row = session.get(Attachment, attachment_id)
        if row is None or row.company_id != company_id:
            raise ValueError("ضمیمه نامعتبر است.")
        row.is_deleted = True
        row.deleted_by_user_id = user_id
        row.deleted_at = datetime.datetime.now()
        session.commit()
