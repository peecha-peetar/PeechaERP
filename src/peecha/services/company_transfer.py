"""ارسال/انتقال/کپیِ اسناد حسابداری به شرکتِ دیگر — طبقِ آیتمِ ۳ (درخواستِ
صریح: «امکانِ ارسالِ اسنادِ حسابداری و انتقال آن‌ها و کپیِ اسناد به شرکتِ
دیگر، به‌همراهِ ضمائم اگر داشته باشد؛ اگر حساب‌ها تعریف نشده باشند لیست
کند و اگر نبود به‌صورتِ اتوماتیک حساب‌ها را هم در شرکت‌ها کپی و انتقال
دهد») + پاسخِ تاییدشده‌یِ کاربر به پرسشِ روشن‌سازی («هر دو حالت،
انتخابی»): کپی (سندِ اصلی دست‌نخورده می‌ماند) یا انتقال (سندِ اصلی در
شرکتِ مبدأ ابطال می‌شود).

طبقِ همان قراردادِ مستندشده در company_cloning.py: تفصیلی‌هایِ اشخاص
(مشتری/تامین‌کننده/پرسنل) رابطه‌یِ تجاریِ مختصِ همان شرکت‌اند، نه بخشی از
کدینگ — پس هرگز خودکار کپی نمی‌شوند؛ اگر سطرِ سندی به یک شخصِ ناموجود در
شرکتِ مقصد نیاز داشته باشد، فقط لیست می‌شود (کاربر باید اول در شرکتِ
مقصد تعریفش کند). حساب‌هایِ کدینگی (گروه/کل/معین) و تفصیلی‌هایِ غیرِشخص
(کالا/بانک/صندوق/مرکزِ هزینه/پروژه/گروه‌هایِ ساده) هرکدام با همان
کد/full_code، به‌همراهِ کلِ زنجیره‌یِ والدشان، در شرکتِ مقصد اگر نبودند
خودکار ساخته می‌شوند."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import JournalEntry, JournalEntryStatus, JournalEntryType
from peecha.db.models.documents import Attachment
from peecha.db.models.security import Form
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import journal_entries as je_service


@dataclass
class MissingAccountRow:
    kind: str  # "GL" | "DETAIL"
    dimension_label: str
    full_code: str
    name: str
    copyable: bool  # False برایِ تفصیلیِ اشخاص — باید دستی در مقصد تعریف شود


def _gl_accounts_used(journal_entry_ids: list[int]) -> dict[int, list]:
    """برایِ هر سند، فهرستِ ردیف‌های واقعیِ آن (LineInput) را برمی‌گرداند."""
    return {jid: je_service.get_journal_entry_lines(jid) for jid in journal_entry_ids}


def preview_transfer(
    source_company_id: int, target_company_id: int, journal_entry_ids: list[int]
) -> list[MissingAccountRow]:
    """حساب‌هایِ کدینگی/تفصیلیِ استفاده‌شده در اسنادِ انتخاب‌شده که در شرکتِ
    مقصد (بر اساسِ full_code/کد) هنوز تعریف نشده‌اند."""
    source_accounts_by_id = {a.account_id: a for a in coa_service.list_accounts(source_company_id)}
    target_full_codes = {a.full_code for a in coa_service.list_accounts(target_company_id)}
    source_details_by_id = {d.detail_account_id: d for d in dimensions_service.list_all_detail_accounts(source_company_id)}
    # طبقِ درخواستِ صریح: کلید شاملِ person_group_code هم هست — چون
    # full_code به‌تنهایی بینِ گروه‌هایِ مختلفِ اشخاص (مثلاً مشتریِ «۰۰۱» و
    # تامین‌کننده‌یِ «۰۰۱») یکتا نیست.
    target_details_by_key = {
        (d.dimension_type_id, d.person_group_code, d.full_code): d
        for d in dimensions_service.list_all_detail_accounts(target_company_id)
    }
    # نگاشتِ نوعِ‌بُعدِ مقصد بر اساسِ کد، برایِ اینکه بشود کلیدِ (dimension_type_id, full_code) را با نوعِ‌بُعدِ *مقصد* ساخت.
    source_type_code_by_id = {
        t.dimension_type_id: t.code for t in dimensions_service.list_dimension_types(source_company_id, include_system=True)
    }
    target_type_id_by_code = {
        t.code: t.dimension_type_id
        for t in dimensions_service.list_dimension_types(target_company_id, include_system=True)
    }

    missing: dict[tuple, MissingAccountRow] = {}
    lines_by_entry = _gl_accounts_used(journal_entry_ids)
    for lines in lines_by_entry.values():
        for line in lines:
            account = source_accounts_by_id.get(line.account_id)
            if account is not None and account.full_code not in target_full_codes:
                for code in _ancestor_full_codes(account.full_code):
                    if code not in target_full_codes and (("GL", code)) not in missing:
                        name = next((a.name for a in source_accounts_by_id.values() if a.full_code == code), code)
                        missing[("GL", code)] = MissingAccountRow("GL", "حسابِ کدینگی", code, name, True)
            for dimension_type_id, detail_account_id in line.details.items():
                detail = source_details_by_id.get(detail_account_id)
                if detail is None:
                    continue
                type_code = source_type_code_by_id.get(dimension_type_id)
                target_type_id = target_type_id_by_code.get(type_code) if type_code else None
                target_key = (target_type_id, detail.person_group_code, detail.full_code) if target_type_id is not None else None
                if target_key is not None and target_key in target_details_by_key:
                    continue
                is_person = detail.person_group_code is not None
                key = ("DETAIL", type_code, detail.person_group_code, detail.full_code)
                if key not in missing:
                    label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(type_code, type_code or "؟")
                    missing[key] = MissingAccountRow(
                        "DETAIL", label, detail.full_code, detail.name or detail.code, not is_person
                    )
    return list(missing.values())


def _ancestor_full_codes(full_code: str) -> list[str]:
    segments = full_code.split("-")
    return ["-".join(segments[: i + 1]) for i in range(len(segments))]


def _ensure_gl_account(
    target_company_id: int,
    source_full_code: str,
    source_accounts_by_full_code: dict[str, "coa_service.AccountRow"],
    target_accounts_by_full_code: dict[str, int],
    language_id: int,
    user_id: int | None,
) -> int:
    existing = target_accounts_by_full_code.get(source_full_code)
    if existing is not None:
        return existing
    source_account = source_accounts_by_full_code[source_full_code]
    segments = source_full_code.split("-")
    parent_account_id = None
    if len(segments) > 1:
        parent_full_code = "-".join(segments[:-1])
        parent_account_id = _ensure_gl_account(
            target_company_id, parent_full_code, source_accounts_by_full_code, target_accounts_by_full_code, language_id, user_id
        )
    created = coa_service.create_account(
        target_company_id,
        segments[-1],
        source_account.name,
        source_account.nature_code,
        source_account.category_code,
        source_account.account_type_code,
        source_account.is_postable,
        language_id,
        parent_account_id=parent_account_id,
        changed_by_user_id=user_id,
        cash_flow_section_code=source_account.cash_flow_section_code,
        liquidity_class_code=source_account.liquidity_class_code,
        balance_sheet_side_code=source_account.balance_sheet_side_code,
    )
    target_accounts_by_full_code[source_full_code] = created.account_id
    return created.account_id


def _ensure_dimension_type(target_company_id: int, code: str, target_type_id_by_code: dict[str, int]) -> int:
    existing = target_type_id_by_code.get(code)
    if existing is not None:
        return existing
    created = dimensions_service.create_dimension_type(target_company_id, code)
    target_type_id_by_code[code] = created.dimension_type_id
    return created.dimension_type_id


def _ensure_detail_account(
    target_company_id: int,
    target_dimension_type_id: int,
    source_full_code: str,
    source_details_by_full_code: dict[str, "dimensions_service.UnifiedDetailAccountRow"],
    target_details_by_full_code: dict[str, int],
) -> int:
    existing = target_details_by_full_code.get(source_full_code)
    if existing is not None:
        return existing
    source_detail = source_details_by_full_code[source_full_code]
    segments = source_full_code.split("-")
    parent_detail_account_id = None
    if len(segments) > 1:
        parent_full_code = "-".join(segments[:-1])
        parent_detail_account_id = _ensure_detail_account(
            target_company_id, target_dimension_type_id, parent_full_code, source_details_by_full_code, target_details_by_full_code
        )
    created = dimensions_service.create_detail_account(
        target_company_id,
        target_dimension_type_id,
        source_detail.code,
        source_detail.name,
        parent_detail_account_id=parent_detail_account_id,
    )
    target_details_by_full_code[source_full_code] = created.detail_account_id
    return created.detail_account_id


def transfer_journal_entries(
    source_company_id: int,
    target_company_id: int,
    journal_entry_ids: list[int],
    user_id: int,
    *,
    void_originals: bool,
    target_language_id: int,
) -> list[int]:
    """کپی/انتقالِ اسنادِ انتخاب‌شده به شرکتِ مقصد؛ حساب‌هایِ کدینگی/تفصیلیِ
    غیرِشخصِ ناموجود در مقصد خودکار ساخته می‌شوند. اگر تفصیلیِ شخصی
    ناموجود باشد، خطا می‌دهد (باید از preview_transfer قبلاً بررسی شده
    باشد و کاربر آن را دستی در مقصد تعریف کرده باشد)."""
    if source_company_id == target_company_id:
        raise ValueError("شرکتِ مبدأ و مقصد نمی‌توانند یکی باشند.")

    with new_session() as session:
        entries = {jid: session.get(JournalEntry, jid) for jid in journal_entry_ids}
        if any(e is None or e.company_id != source_company_id for e in entries.values()):
            raise ValueError("یکی از اسنادِ انتخاب‌شده نامعتبر است.")
        if void_originals:
            temporary_status_id = session.scalar(select(JournalEntryStatus.status_id).where(JournalEntryStatus.code == "TEMPORARY"))
            if any(e.status_id != temporary_status_id for e in entries.values()):
                raise ValueError("فقط اسنادِ موقت را می‌توان «انتقال» داد (نه کپی) — سندِ دائم را نمی‌توان ابطال کرد.")
        journal_entry_form_id = session.scalar(select(Form.form_id).where(Form.code == "journal_entry"))
        entry_type_code_by_id = {t.entry_type_id: t.code for t in session.scalars(select(JournalEntryType)).all()}
        entry_infos = {
            jid: (e.document_date, e.description, entry_type_code_by_id.get(e.entry_type_id, "NORMAL"), e.permanent_no or e.temporary_no)
            for jid, e in entries.items()
        }

    source_accounts_by_full_code = {a.full_code: a for a in coa_service.list_accounts(source_company_id)}
    source_accounts_by_full_code_by_id = {a.account_id: a.full_code for a in source_accounts_by_full_code.values()}
    target_accounts_by_full_code = {a.full_code: a.account_id for a in coa_service.list_accounts(target_company_id)}
    source_details_by_id = {d.detail_account_id: d for d in dimensions_service.list_all_detail_accounts(source_company_id)}
    source_details_by_full_code_per_type: dict[int, dict[str, "dimensions_service.UnifiedDetailAccountRow"]] = {}
    for d in dimensions_service.list_all_detail_accounts(source_company_id):
        source_details_by_full_code_per_type.setdefault(d.dimension_type_id, {})[d.full_code] = d
    source_type_code_by_id = {
        t.dimension_type_id: t.code for t in dimensions_service.list_dimension_types(source_company_id, include_system=True)
    }
    target_type_id_by_code = {
        t.code: t.dimension_type_id
        for t in dimensions_service.list_dimension_types(target_company_id, include_system=True)
    }
    target_details_by_full_code_per_type: dict[int, dict[str, int]] = {}
    # طبقِ preview_transfer: کلیدِ مطابقتِ تفصیلیِ اشخاص شاملِ person_group_code
    # هم هست — full_code به‌تنهایی بینِ گروه‌هایِ مختلفِ اشخاص (مثلاً مشتریِ
    # «۰۰۱» و تامین‌کننده‌یِ «۰۰۱») یکتا نیست.
    target_persons_by_key: dict[tuple[int, str | None, str], int] = {}
    for d in dimensions_service.list_all_detail_accounts(target_company_id):
        target_details_by_full_code_per_type.setdefault(d.dimension_type_id, {})[d.full_code] = d.detail_account_id
        if d.person_group_code is not None:
            target_persons_by_key[(d.dimension_type_id, d.person_group_code, d.full_code)] = d.detail_account_id

    # ردیفِ سیستمیِ «بدون تفصیلی» (پیش‌فرضِ بُعدِ اشخاص، طبقِ همان قراردادِ
    # مستندشده در journal_entries.py که برای هر ردیفِ بدونِ تفصیلیِ شخص
    # خودکار اضافه می‌شود) از list_all_detail_accounts حذف می‌شود؛ پس باید
    # جدا (و بدونِ کپی‌کردن) به معادلِ خودش در مقصد نگاشت شود.
    source_no_detail_id = dimensions_service.get_no_detail_account_id(source_company_id)
    target_no_detail_id = dimensions_service.get_no_detail_account_id(target_company_id)
    # get_no_detail_account_id چه‌بسا بُعدِ PERSون را تازه در مقصد ساخته باشد
    # (شرکتِ مقصدِ کاملاً تازه) — چون این اتفاق بعدِ گرفتنِ عکسِ
    # target_type_id_by_code رخ می‌دهد، باید کش هم به‌روز شود، وگرنه
    # _ensure_dimension_type دوباره می‌سازدش و به خطایِ یکتاییِ کد می‌خورد.
    target_type_id_by_code.setdefault("PERSON", dimensions_service.get_person_dimension_type_id(target_company_id))

    def resolve_account(source_account_id: int) -> int:
        source_full_code = source_accounts_by_full_code_by_id[source_account_id]
        return _ensure_gl_account(
            target_company_id, source_full_code, source_accounts_by_full_code, target_accounts_by_full_code,
            target_language_id, user_id,
        )

    def resolve_detail(dimension_type_id: int, detail_account_id: int) -> int:
        if detail_account_id == source_no_detail_id:
            return target_no_detail_id
        detail = source_details_by_id[detail_account_id]
        type_code = source_type_code_by_id[dimension_type_id]
        if detail.person_group_code is not None:
            # تفصیلیِ شخص هرگز خودکار کپی نمی‌شود، اما اگر کاربر از قبل
            # (دستی، طبقِ پیش‌نمایشِ preview_transfer) همان شخص را با همان
            # full_code در شرکتِ مقصد تعریف کرده باشد، باید resolve شود —
            # نه اینکه همیشه خطا بدهد.
            target_dimension_type_id = target_type_id_by_code.get(type_code)
            existing = (
                target_persons_by_key.get((target_dimension_type_id, detail.person_group_code, detail.full_code))
                if target_dimension_type_id is not None
                else None
            )
            if existing is None:
                raise ValueError(
                    f"تفصیلیِ «{detail.name or detail.code}» یک شخص (مشتری/تامین‌کننده/پرسنل) است — "
                    "باید پیش از انتقال، دستی در شرکتِ مقصد تعریف شود."
                )
            return existing
        target_dimension_type_id = _ensure_dimension_type(target_company_id, type_code, target_type_id_by_code)
        target_details_by_full_code = target_details_by_full_code_per_type.setdefault(target_dimension_type_id, {})
        source_details_by_full_code = source_details_by_full_code_per_type[dimension_type_id]
        return _ensure_detail_account(
            target_company_id, target_dimension_type_id, detail.full_code, source_details_by_full_code, target_details_by_full_code
        )

    new_entry_ids: list[int] = []
    for jid in journal_entry_ids:
        document_date, source_description, entry_type_code, source_no = entry_infos[jid]
        lines = je_service.get_journal_entry_lines(jid)
        new_lines = []
        for line in lines:
            new_details = {}
            for dimension_type_id, detail_account_id in line.details.items():
                new_details[
                    _ensure_dimension_type(
                        target_company_id, source_type_code_by_id[dimension_type_id], target_type_id_by_code
                    )
                ] = resolve_detail(dimension_type_id, detail_account_id)
            new_lines.append(
                je_service.LineInput(
                    account_id=resolve_account(line.account_id),
                    description=line.description,
                    debit=line.debit,
                    credit=line.credit,
                    details=new_details,
                    currency_id=line.currency_id,
                    exchange_rate=line.exchange_rate,
                    tax_code=line.tax_code,
                )
            )

        description = f"{source_description or ''} (منتقل‌شده از شرکتِ مبدأ، سندِ شماره‌یِ {source_no})".strip()
        result = je_service.create_journal_entry(
            target_company_id, user_id, document_date, description, new_lines, entry_type_code=entry_type_code
        )
        new_entry_ids.append(result.journal_entry_id)

        if journal_entry_form_id is not None:
            with new_session() as session:
                attachments = session.scalars(
                    select(Attachment).where(
                        Attachment.form_id == journal_entry_form_id,
                        Attachment.source_record_id == jid,
                        Attachment.is_deleted.is_(False),
                    )
                ).all()
                for att in attachments:
                    session.add(
                        Attachment(
                            company_id=target_company_id,
                            form_id=journal_entry_form_id,
                            source_record_id=result.journal_entry_id,
                            file_name=att.file_name,
                            file_extension=att.file_extension,
                            file_size_bytes=att.file_size_bytes,
                            storage_key=att.storage_key,
                            content_sha256=att.content_sha256,
                            uploaded_by_user_id=user_id,
                        )
                    )
                session.commit()

    if void_originals:
        with new_session() as session:
            temporary_status = session.scalar(select(JournalEntryStatus).where(JournalEntryStatus.code == "TEMPORARY"))
            cancelled_status = session.scalar(select(JournalEntryStatus).where(JournalEntryStatus.code == "CANCELLED"))
            for jid in journal_entry_ids:
                original = session.get(JournalEntry, jid)
                if original.status_id != temporary_status.status_id:
                    raise ValueError("فقط اسنادِ موقت را می‌توان «انتقال» داد (نه کپی) — سندِ دائم را نمی‌توان ابطال کرد.")
                original.status_id = cancelled_status.status_id
            session.commit()

    return new_entry_ids
