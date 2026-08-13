"""سرویس کدینگ حسابداری — درخت سه‌سطحی گروه/کل/معین.

سطح از روی والدِ انتخابی محاسبه می‌شود (نه ورودی کاربر): بدون والد یعنی
سطح ۱ (گروه)، والدِ سطح ۱ یعنی سطح ۲ (کل)، والدِ سطح ۲ یعنی سطح ۳ (معین).
معین دیگر نمی‌تواند زیرشاخه بگیرد — طبق طراحی دیتابیس (account_level) که
فقط ۳ سطح را در نظر گرفته.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.accounting import (
    AccountCategory,
    AccountNature,
    AccountType,
    BalanceSheetSide,
    CashFlowSection,
    ChartOfAccount,
    ChartOfAccountLevelConfig,
    JournalEntryLine,
    LiquidityClass,
)
from peecha.db.models.core import Translation
from peecha.services import audit as audit_service

MAX_ACCOUNT_LEVEL = 3


@dataclass
class AccountRow:
    account_id: int
    full_code: str
    name: str
    account_level: int
    is_postable: bool
    nature_code: str
    category_code: str
    account_type_code: str
    cash_flow_section_code: str | None = None
    liquidity_class_code: str | None = None
    balance_sheet_side_code: str | None = None


def list_accounts(company_id: int) -> list[AccountRow]:
    with new_session() as session:
        accounts = session.scalars(
            select(ChartOfAccount)
            .where(ChartOfAccount.company_id == company_id)
            .order_by(ChartOfAccount.full_code)
        ).all()
        account_ids = [a.account_id for a in accounts]
        names: dict[int, str] = {}
        if account_ids:
            rows = session.execute(
                select(Translation.entity_id, Translation.value).where(
                    Translation.entity_type == "ChartOfAccount",
                    Translation.entity_id.in_(account_ids),
                    Translation.property_name == "Name",
                )
            ).all()
            names = dict(rows)

        nature_codes = dict(session.execute(select(AccountNature.nature_id, AccountNature.code)).all())
        category_codes = dict(session.execute(select(AccountCategory.category_id, AccountCategory.code)).all())
        account_type_codes = dict(session.execute(select(AccountType.account_type_id, AccountType.code)).all())
        cash_flow_section_codes = dict(
            session.execute(select(CashFlowSection.cash_flow_section_id, CashFlowSection.code)).all()
        )
        liquidity_class_codes = dict(
            session.execute(select(LiquidityClass.liquidity_class_id, LiquidityClass.code)).all()
        )
        balance_sheet_side_codes = dict(
            session.execute(select(BalanceSheetSide.balance_sheet_side_id, BalanceSheetSide.code)).all()
        )

        return [
            AccountRow(
                account_id=a.account_id,
                full_code=a.full_code,
                name=names.get(a.account_id, a.segment_code),
                account_level=a.account_level,
                is_postable=a.is_postable,
                nature_code=nature_codes[a.nature_id],
                category_code=category_codes[a.category_id],
                account_type_code=account_type_codes[a.account_type_id],
                cash_flow_section_code=cash_flow_section_codes.get(a.cash_flow_section_id),
                liquidity_class_code=liquidity_class_codes.get(a.liquidity_class_id),
                balance_sheet_side_code=balance_sheet_side_codes.get(a.balance_sheet_side_id),
            )
            for a in accounts
        ]


def list_postable_accounts(company_id: int) -> list[AccountRow]:
    """فقط حساب‌های قابل‌ثبت‌سند (معمولاً سطح معین) — برای انتخابگرِ ردیف سند."""
    return [row for row in list_accounts(company_id) if row.is_postable]


def _validate_segment_code(session, company_id: int, account_level: int, segment_code: str) -> None:
    """اگر برایِ این سطح تنظیماتِ رقم/بازه در acc.chart_of_account_level_config
    وجود داشته باشد (اختیاری)، کدِ واردشده باید دقیقاً همان طول و (اگر بازه
    هم تنظیم شده) رقمی و در همان بازه باشد. طبقِ درخواستِ صریح، این تنظیمات
    از ابتدا ست می‌شوند و بعدِ اولین سندِ شرکت دیگر قابلِ‌تغییر نیستند."""
    level_config = session.get(ChartOfAccountLevelConfig, (company_id, account_level))
    if level_config is None:
        return
    if level_config.code_length is not None and len(segment_code) != level_config.code_length:
        raise ValueError(f"طولِ کدِ سطحِ {account_level} باید دقیقاً {level_config.code_length} رقم باشد.")
    if level_config.range_from is not None or level_config.range_to is not None:
        if not segment_code.isdigit():
            raise ValueError(f"کدِ سطحِ {account_level} باید رقمی باشد (بازه‌ی از-تا تنظیم شده).")
        value = int(segment_code)
        if level_config.range_from is not None and value < level_config.range_from:
            raise ValueError(f"کدِ سطحِ {account_level} باید حداقل {level_config.range_from} باشد.")
        if level_config.range_to is not None and value > level_config.range_to:
            raise ValueError(f"کدِ سطحِ {account_level} باید حداکثر {level_config.range_to} باشد.")


def create_account(
    company_id: int,
    segment_code: str,
    name: str,
    nature_code: str,
    category_code: str,
    account_type_code: str,
    is_postable: bool,
    language_id: int,
    parent_account_id: int | None = None,
    changed_by_user_id: int | None = None,
    cash_flow_section_code: str | None = None,
    liquidity_class_code: str | None = None,
    balance_sheet_side_code: str | None = None,
) -> ChartOfAccount:
    with new_session() as session:
        # طبقِ درخواستِ صریح: ماهیت/دسته/نوعِ حساب فقط در سطحِ گروه (بدونِ
        # والد) انتخاب می‌شود — هر زیرشاخه (کل/معین) همین سه مقدار را از
        # والدِ خودش به‌ارث می‌برد؛ مقدارهایِ ورودی برایِ زیرشاخه‌ها نادیده
        # گرفته می‌شوند تا کل زیردرخت همیشه با گروهِ خودش هم‌خوان بماند.
        # طبقِ‌بالا، بخشِ وجوهِ نقد (cash_flow_section) هم از همان الگو
        # پیروی می‌کند، با این فرق که nullable است (بدونِ طبقه‌بندی مجاز است).
        if parent_account_id is None:
            account_level = 1
            full_code = segment_code
            nature = session.scalar(select(AccountNature).where(AccountNature.code == nature_code))
            category = session.scalar(select(AccountCategory).where(AccountCategory.code == category_code))
            account_type = session.scalar(select(AccountType).where(AccountType.code == account_type_code))
            if nature is None or category is None or account_type is None:
                raise ValueError("مقدار ماهیت/دسته/نوع حساب نامعتبر است.")
            nature_id, category_id, account_type_id = nature.nature_id, category.category_id, account_type.account_type_id
            cash_flow_section_id = None
            if cash_flow_section_code:
                cash_flow_section = session.scalar(
                    select(CashFlowSection).where(CashFlowSection.code == cash_flow_section_code)
                )
                if cash_flow_section is None:
                    raise ValueError("مقدارِ بخشِ وجوهِ نقد نامعتبر است.")
                cash_flow_section_id = cash_flow_section.cash_flow_section_id
            liquidity_class_id = None
            if liquidity_class_code:
                liquidity_class = session.scalar(
                    select(LiquidityClass).where(LiquidityClass.code == liquidity_class_code)
                )
                if liquidity_class is None:
                    raise ValueError("مقدارِ طبقه‌یِ نقدینگی نامعتبر است.")
                liquidity_class_id = liquidity_class.liquidity_class_id
            balance_sheet_side_id = None
            if balance_sheet_side_code:
                balance_sheet_side = session.scalar(
                    select(BalanceSheetSide).where(BalanceSheetSide.code == balance_sheet_side_code)
                )
                if balance_sheet_side is None:
                    raise ValueError("مقدارِ سمتِ ترازنامه نامعتبر است.")
                balance_sheet_side_id = balance_sheet_side.balance_sheet_side_id
        else:
            parent = session.get(ChartOfAccount, parent_account_id)
            if parent is None or parent.company_id != company_id:
                raise ValueError("حساب والد نامعتبر است.")
            if parent.account_level >= MAX_ACCOUNT_LEVEL:
                raise ValueError("حساب سطح معین دیگر نمی‌تواند زیرشاخه بگیرد.")
            account_level = parent.account_level + 1
            full_code = f"{parent.full_code}-{segment_code}"
            nature_id, category_id, account_type_id = parent.nature_id, parent.category_id, parent.account_type_id
            cash_flow_section_id = parent.cash_flow_section_id
            liquidity_class_id = parent.liquidity_class_id
            balance_sheet_side_id = parent.balance_sheet_side_id

        # طبقِ درخواستِ صریح: فقط حساب‌هایِ سطحِ آخر (معین) قابلِ ثبتِ سندند —
        # چون افزودنِ زیرشاخه به سطحِ آخر از قبل مسدود است، این تضمین می‌کند
        # حساب‌هایِ postable همیشه برگ بمانند.
        if is_postable and account_level != MAX_ACCOUNT_LEVEL:
            raise ValueError(f"فقط حساب‌هایِ سطحِ {MAX_ACCOUNT_LEVEL} (معین) می‌توانند قابلِ ثبتِ سند باشند.")

        _validate_segment_code(session, company_id, account_level, segment_code)

        account = ChartOfAccount(
            company_id=company_id,
            parent_account_id=parent_account_id,
            segment_code=segment_code,
            full_code=full_code,
            account_level=account_level,
            nature_id=nature_id,
            category_id=category_id,
            account_type_id=account_type_id,
            cash_flow_section_id=cash_flow_section_id,
            liquidity_class_id=liquidity_class_id,
            balance_sheet_side_id=balance_sheet_side_id,
            is_postable=is_postable,
        )
        session.add(account)
        session.flush()

        session.add(
            Translation(
                entity_type="ChartOfAccount",
                entity_id=account.account_id,
                property_name="Name",
                language_id=language_id,
                value=name,
            )
        )

        # طبقِ‌بالا: برایِ زیرشاخه‌ها مقدارهایِ اعمال‌شده از والد به‌ارث
        # رسیده‌اند (نه لزوماً همان nature_code/... ورودی) — برایِ ثبتِ
        # درستِ رخداد در ردِ حسابرسی، کدهایِ واقعاً اعمال‌شده جدا خوانده می‌شوند.
        applied_nature = session.get(AccountNature, nature_id)
        applied_category = session.get(AccountCategory, category_id)
        applied_account_type = session.get(AccountType, account_type_id)

        audit_service.log_activity(
            session,
            company_id=company_id,
            user_id=changed_by_user_id,
            entity_type="ChartOfAccount",
            entity_id=account.account_id,
            action="CREATE",
            changes={
                "after": {
                    "full_code": full_code,
                    "name": name,
                    "nature_code": applied_nature.code,
                    "category_code": applied_category.code,
                    "account_type_code": applied_account_type.code,
                    "is_postable": is_postable,
                }
            },
        )

        session.commit()
        session.refresh(account)
        session.expunge(account)
        return account


def _descendant_accounts(session, account_id: int) -> list[ChartOfAccount]:
    """همه‌ی زیرشاخه‌هایِ این حساب (فرزند و نوه، به‌صورتِ بازگشتی) —
    برایِ کَسکِیدکردنِ ماهیت/دسته/نوعِ حسابِ سطحِ گروه به کلِ زیردرخت."""
    result: list[ChartOfAccount] = []
    frontier = [account_id]
    while frontier:
        children = session.scalars(
            select(ChartOfAccount).where(ChartOfAccount.parent_account_id.in_(frontier))
        ).all()
        result.extend(children)
        frontier = [c.account_id for c in children]
    return result


def update_account(
    account_id: int,
    company_id: int,
    name: str,
    nature_code: str,
    category_code: str,
    account_type_code: str,
    is_postable: bool,
    language_id: int,
    changed_by_user_id: int | None = None,
    cash_flow_section_code: str | None = None,
    liquidity_class_code: str | None = None,
    balance_sheet_side_code: str | None = None,
) -> ChartOfAccount:
    """ویرایشِ حساب — عمداً فقط نام/ماهیت/دسته/نوع/قابل‌ثبت‌بودن قابل‌تغییرند؛
    کد و والد (که full_code و سطحِ کل زیردرخت را تعیین می‌کنند) در این
    نسخه ثابت می‌مانند تا ویرایش نیاز به بازمحاسبه‌ی زنجیره‌ای نداشته باشد.

    طبقِ درخواستِ صریح: اگر این حساب حتی یک سطرِ سند داشته باشد، اصلاً
    قابلِ‌ویرایش نیست (نه فقط کد/والد که از قبل ثابت بودند).

    طبقِ درخواستِ صریحِ بعدی: ماهیت/دسته/نوعِ حساب فقط رویِ حسابِ سطحِ گروه
    (بدونِ والد) قابلِ‌تغییرند — هر زیرشاخه (کل/معین) این سه مقدار را از
    والدِ خودش به‌ارث می‌برد و نمی‌تواند مستقل از آن تغییر کند. با ویرایشِ
    یک حسابِ گروه، این سه مقدار رویِ کلِ زیردرخت (کل‌ها و معین‌هایِ زیرش)
    هم به‌روزرسانی می‌شود.

    طبقِ درخواستِ صریحِ بعدی‌تر: این ویرایش/کَسکید باید «در هر حالتی»
    ممکن باشد — حتی اگر یکی از زیرشاخه‌ها از قبل سند داشته باشد (چک/ردِ
    قبلی که کلِ عملیات را در آن حالت رد می‌کرد، حذف شد؛ فقط ویرایشِ خودِ
    این حسابِ مشخص، اگر مستقیماً سند داشته باشد، طبقِ قاعده‌یِ بالاترِ
    همین تابع همچنان رد می‌شود — آن قاعده مستقل و بدون‌تغییر است)."""
    with new_session() as session:
        account = session.get(ChartOfAccount, account_id)
        if account is None or account.company_id != company_id:
            raise ValueError("حساب نامعتبر است.")

        line_count = session.scalar(
            select(func.count()).select_from(JournalEntryLine).where(JournalEntryLine.account_id == account_id)
        )
        if line_count:
            raise ValueError("این حساب در سندهای حسابداری استفاده شده؛ قابلِ‌ویرایش نیست.")

        if is_postable and account.account_level != MAX_ACCOUNT_LEVEL:
            raise ValueError(f"فقط حساب‌هایِ سطحِ {MAX_ACCOUNT_LEVEL} (معین) می‌توانند قابلِ ثبتِ سند باشند.")

        descendants: list[ChartOfAccount] = []
        if account.parent_account_id is not None:
            # زیرشاخه: ماهیت/دسته/نوع/بخشِ وجوهِ نقد مستقل نیست — همیشه با
            # والدِ فعلی هم‌خوان می‌ماند، صرفِ‌نظر از ورودیِ کاربر.
            parent = session.get(ChartOfAccount, account.parent_account_id)
            nature_id, category_id, account_type_id = parent.nature_id, parent.category_id, parent.account_type_id
            cash_flow_section_id = parent.cash_flow_section_id
            liquidity_class_id = parent.liquidity_class_id
            balance_sheet_side_id = parent.balance_sheet_side_id
        else:
            nature = session.scalar(select(AccountNature).where(AccountNature.code == nature_code))
            category = session.scalar(select(AccountCategory).where(AccountCategory.code == category_code))
            account_type = session.scalar(select(AccountType).where(AccountType.code == account_type_code))
            if nature is None or category is None or account_type is None:
                raise ValueError("مقدار ماهیت/دسته/نوع حساب نامعتبر است.")
            nature_id, category_id, account_type_id = nature.nature_id, category.category_id, account_type.account_type_id
            cash_flow_section_id = None
            if cash_flow_section_code:
                cash_flow_section = session.scalar(
                    select(CashFlowSection).where(CashFlowSection.code == cash_flow_section_code)
                )
                if cash_flow_section is None:
                    raise ValueError("مقدارِ بخشِ وجوهِ نقد نامعتبر است.")
                cash_flow_section_id = cash_flow_section.cash_flow_section_id
            liquidity_class_id = None
            if liquidity_class_code:
                liquidity_class = session.scalar(
                    select(LiquidityClass).where(LiquidityClass.code == liquidity_class_code)
                )
                if liquidity_class is None:
                    raise ValueError("مقدارِ طبقه‌یِ نقدینگی نامعتبر است.")
                liquidity_class_id = liquidity_class.liquidity_class_id
            balance_sheet_side_id = None
            if balance_sheet_side_code:
                balance_sheet_side = session.scalar(
                    select(BalanceSheetSide).where(BalanceSheetSide.code == balance_sheet_side_code)
                )
                if balance_sheet_side is None:
                    raise ValueError("مقدارِ سمتِ ترازنامه نامعتبر است.")
                balance_sheet_side_id = balance_sheet_side.balance_sheet_side_id

            # طبقِ درخواستِ صریح: ویرایشِ ماهیت/دسته/نوع/بخشِ‌وجوهِ‌نقد/طبقه‌یِ‌نقدینگیِ
            # گروه، در هر حالتی مجاز است و رویِ کلِ زیردرخت (کل/معین‌هایِ
            # زیرش) کَسکید می‌شود — حتی اگر زیرشاخه‌ای از قبل سند داشته
            # باشد؛ دیگر رد نمی‌شود.
            descendants = _descendant_accounts(session, account_id)

        before_nature_id, before_category_id = account.nature_id, account.category_id
        before_account_type_id, before_is_postable = account.account_type_id, account.is_postable

        account.nature_id = nature_id
        account.category_id = category_id
        account.account_type_id = account_type_id
        account.cash_flow_section_id = cash_flow_section_id
        account.liquidity_class_id = liquidity_class_id
        account.balance_sheet_side_id = balance_sheet_side_id
        account.is_postable = is_postable
        for descendant in descendants:
            descendant.nature_id = nature_id
            descendant.category_id = category_id
            descendant.account_type_id = account_type_id
            descendant.cash_flow_section_id = cash_flow_section_id
            descendant.liquidity_class_id = liquidity_class_id
            descendant.balance_sheet_side_id = balance_sheet_side_id

        translation = session.scalar(
            select(Translation).where(
                Translation.entity_type == "ChartOfAccount",
                Translation.entity_id == account_id,
                Translation.property_name == "Name",
                Translation.language_id == language_id,
            )
        )
        before_name = translation.value if translation is not None else None
        if translation is None:
            session.add(
                Translation(
                    entity_type="ChartOfAccount",
                    entity_id=account_id,
                    property_name="Name",
                    language_id=language_id,
                    value=name,
                )
            )
        else:
            translation.value = name

        audit_service.log_activity(
            session,
            company_id=company_id,
            user_id=changed_by_user_id,
            entity_type="ChartOfAccount",
            entity_id=account_id,
            action="UPDATE",
            changes={
                "before": {
                    "name": before_name,
                    "nature_id": before_nature_id,
                    "category_id": before_category_id,
                    "account_type_id": before_account_type_id,
                    "is_postable": before_is_postable,
                },
                "after": {
                    "name": name,
                    "nature_id": nature_id,
                    "category_id": category_id,
                    "account_type_id": account_type_id,
                    "is_postable": is_postable,
                },
            },
        )
        if descendants:
            audit_service.log_activity(
                session,
                company_id=company_id,
                user_id=changed_by_user_id,
                entity_type="ChartOfAccount",
                entity_id=account_id,
                action="UPDATE",
                changes={
                    "after": {
                        "cascaded_nature_category_type_to_descendants": [d.account_id for d in descendants],
                    }
                },
            )

        session.commit()
        session.refresh(account)
        session.expunge(account)
        return account


def delete_account(account_id: int, company_id: int, changed_by_user_id: int | None = None) -> None:
    with new_session() as session:
        account = session.get(ChartOfAccount, account_id)
        if account is None or account.company_id != company_id:
            raise ValueError("حساب نامعتبر است.")

        child_count = session.scalar(
            select(func.count()).select_from(ChartOfAccount).where(ChartOfAccount.parent_account_id == account_id)
        )
        if child_count:
            raise ValueError("این حساب زیرشاخه دارد؛ اول زیرشاخه‌ها را حذف کنید.")

        line_count = session.scalar(
            select(func.count()).select_from(JournalEntryLine).where(JournalEntryLine.account_id == account_id)
        )
        if line_count:
            raise ValueError("این حساب در سندهای حسابداری استفاده شده؛ قابل حذف نیست.")

        audit_service.log_activity(
            session,
            company_id=company_id,
            user_id=changed_by_user_id,
            entity_type="ChartOfAccount",
            entity_id=account_id,
            action="DELETE",
            changes={"before": {"full_code": account.full_code, "is_postable": account.is_postable}},
        )

        session.execute(
            Translation.__table__.delete().where(
                Translation.entity_type == "ChartOfAccount",
                Translation.entity_id == account_id,
            )
        )
        session.delete(account)
        session.commit()


def account_has_posted_lines(account_id: int) -> bool:
    """برایِ UI: پیش از تلاشِ ذخیره، فرم را غیرفعال کند اگر این حساب سند
    دارد — منبعِ حقیقتِ نهایی همچنان چکِ داخلِ update_account است."""
    with new_session() as session:
        return (
            session.scalar(
                select(func.count()).select_from(JournalEntryLine).where(JournalEntryLine.account_id == account_id)
            )
            > 0
        )


@dataclass
class AccountLevelConfigRow:
    account_level: int
    code_length: int | None
    range_from: int | None
    range_to: int | None


def list_account_level_config(company_id: int) -> list[AccountLevelConfigRow]:
    with new_session() as session:
        rows = session.scalars(
            select(ChartOfAccountLevelConfig)
            .where(ChartOfAccountLevelConfig.company_id == company_id)
            .order_by(ChartOfAccountLevelConfig.account_level)
        ).all()
        return [
            AccountLevelConfigRow(
                account_level=r.account_level, code_length=r.code_length, range_from=r.range_from, range_to=r.range_to
            )
            for r in rows
        ]


_ACCOUNT_LEVEL_NAMES = {1: "گروه", 2: "کل", 3: "معین"}


def account_level_has_accounts(company_id: int, account_level: int) -> bool:
    """آیا حداقل یک حسابِ کدینگ‌شده در این سطح از قبل وجود دارد — طبقِ
    درخواستِ صریح، تعدادِ رقم/بازه‌یِ هر سطح به‌محضِ اینکه خودِ آن سطح
    حساب داشته باشد قفل می‌شود؛ نه فقط وقتی کلِ شرکت سندِ حسابداری دارد
    (چون تغییرِ طولِ کد بعدِ ساختنِ حساب‌ها با آن طول، کدهایِ موجود را
    ناسازگار می‌کند، حتی اگر هنوز هیچ سندی ثبت نشده باشد)."""
    with new_session() as session:
        count = session.scalar(
            select(func.count())
            .select_from(ChartOfAccount)
            .where(ChartOfAccount.company_id == company_id, ChartOfAccount.account_level == account_level)
        )
        return bool(count)


def get_locked_account_levels(company_id: int) -> set[int]:
    """سطح‌هایی که تعدادِ رقم/بازه‌شان دیگر قابلِ‌تغییر نیست — طبقِ بازخوردِ
    صریح، فقط بر اساسِ اینکه خودِ آن سطح حساب دارد یا نه (نه اینکه کلِ
    شرکت سند دارد یا نه؛ سندها به شناسه‌یِ حساب وصل‌اند نه به طولِ کد،
    پس سطحی که الان هیچ حسابی ندارد، حتی اگر جایِ دیگرِ شرکت سند ثبت شده
    باشد، بی‌خطر قابلِ‌تغییر است)."""
    return {level for level in range(1, MAX_ACCOUNT_LEVEL + 1) if account_level_has_accounts(company_id, level)}


def set_account_level_config(company_id: int, levels: dict[int, dict]) -> None:
    """جایگزینیِ کاملِ تنظیماتِ کدینگِ حساب‌ها — levels یعنی {شماره‌ی سطح
    (۱ تا ۳): {"code_length": ..|None, "range_from": ..|None, "range_to":
    ..|None}}. طبقِ درخواستِ صریح: «تعداد ارقام حساب‌ها از ابتدا ست شود و
    اگر سندی ثبت شود دیگر قابل تغییر نباشد» — و طبقِ بازخوردِ بعدی، هر
    سطح به‌محضِ اینکه *خودش* حساب داشته باشد قفل می‌شود؛ صرفاً وجودِ سندِ
    حسابداری در جایِ دیگرِ شرکت (بدونِ ربط به این سطح) دیگر مانعِ ذخیره
    نیست، چون سندها به شناسه‌یِ حساب وصل‌اند نه طولِ کد."""
    with new_session() as session:

        # نکته: با select(...) رویِ ستون‌هایِ خام (نه select(ChartOfAccountLevelConfig))
        # هیچ آبجکتِ ORM‌ای در identity mapِ سشن ثبت نمی‌شود — وگرنه پایین‌تر
        # که همین ردیف‌ها را bulk-delete و دوباره با همان PK می‌سازیم،
        # SQLAlchemy هشدارِ «identity map conflict» می‌داد.
        existing_by_level = {
            row.account_level: row
            for row in session.execute(
                select(
                    ChartOfAccountLevelConfig.account_level,
                    ChartOfAccountLevelConfig.code_length,
                    ChartOfAccountLevelConfig.range_from,
                    ChartOfAccountLevelConfig.range_to,
                ).where(ChartOfAccountLevelConfig.company_id == company_id)
            ).all()
        }

        for account_level, config in levels.items():
            if not (1 <= account_level <= MAX_ACCOUNT_LEVEL):
                raise ValueError(f"شماره‌ی سطح باید بینِ ۱ تا {MAX_ACCOUNT_LEVEL} باشد.")
            code_length = config.get("code_length")
            if code_length is not None and not (1 <= code_length <= 10):
                raise ValueError("تعدادِ رقمِ کد باید بینِ ۱ تا ۱۰ باشد.")
            range_from = config.get("range_from")
            range_to = config.get("range_to")
            if range_from is not None and range_to is not None and range_from > range_to:
                raise ValueError("مقدارِ «از» نمی‌تواند بزرگ‌تر از «تا» باشد.")
            if code_length is not None:
                max_value = 10**code_length - 1
                if range_from is not None and range_from > max_value:
                    raise ValueError(
                        f"مقدارِ «از» در سطحِ {account_level} نمی‌تواند بیشتر از {max_value} باشد "
                        f"(تعدادِ رقمِ این سطح {code_length} رقم است)."
                    )
                if range_to is not None and range_to > max_value:
                    raise ValueError(
                        f"مقدارِ «تا» در سطحِ {account_level} نمی‌تواند بیشتر از {max_value} باشد "
                        f"(تعدادِ رقمِ این سطح {code_length} رقم است)."
                    )

            existing = existing_by_level.get(account_level)
            existing_code_length = existing.code_length if existing else None
            existing_range_from = existing.range_from if existing else None
            existing_range_to = existing.range_to if existing else None
            changed = (
                code_length != existing_code_length
                or range_from != existing_range_from
                or range_to != existing_range_to
            )
            if changed and account_level_has_accounts(company_id, account_level):
                level_name = _ACCOUNT_LEVEL_NAMES.get(account_level, str(account_level))
                raise ValueError(
                    f"برایِ سطحِ «{level_name}» قبلاً حساب تعریف شده؛ تعدادِ رقم/بازه‌یِ این سطح دیگر قابلِ‌تغییر نیست."
                )

        session.execute(
            ChartOfAccountLevelConfig.__table__.delete().where(ChartOfAccountLevelConfig.company_id == company_id)
        )
        for account_level, config in levels.items():
            code_length = config.get("code_length")
            range_from = config.get("range_from")
            range_to = config.get("range_to")
            if code_length is None and range_from is None and range_to is None:
                continue
            session.add(
                ChartOfAccountLevelConfig(
                    company_id=company_id,
                    account_level=account_level,
                    code_length=code_length,
                    range_from=range_from,
                    range_to=range_to,
                )
            )
        session.commit()
