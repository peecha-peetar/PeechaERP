"""فرمِ واحدِ دریافت/پرداختِ چندروشی — یک طرف‌حساب + چند ردیفِ روش (نقد/
بانک/چک/تخفیف/کالابرگ/بن)، هرکدام طبقِ نگاشتِ تنظیماتِ خزانه‌داری به
حسابِ خودش می‌رود و همه در یک سندِ حسابداریِ واحد ثبت می‌شوند
(services/treasury.create_treasury_voucher). طبقِ درخواستِ صریح: «دریافت
از آقایِ ایکس مبلغِ ۲۰۰۰ که در فرم مشخص بشه نقدی یا بانک یا چک یا در
قالبِ تخفیف»."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import QEvent, QMarginsF, Qt, QTimer, Signal
from PySide6.QtGui import QPageLayout, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import currencies as currencies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import installments as installments_service
from peecha.services import treasury as treasury_service
from peecha.ui import theme
from peecha.ui.main import get_font_family
from peecha.ui.screens.journal_entry import _AmountField, _fill_options, _make_searchable_combo
from peecha.ui.widgets import (
    FieldGrid,
    FieldHelpMixin,
    FieldSpec,
    FormScreenBase,
    JalaliDateEdit,
    LayoutEditMixin,
    PersianDigitLineEdit,
    SectionStepper,
    SummaryCard,
    SummaryCardBar,
)

_METHOD_LABELS = {
    "CASH": "نقدی",
    "BANK": "بانکی",
    "CHECK": "چک",
    "DISCOUNT": "تخفیف",
    "GOODS_COUPON": "کالابرگ",
    "VOUCHER": "بن",
    "NETTING": "تهاتر",
    "CHECK_DISBURSEMENT": "پرداخت با چکِ دریافتی (خرجِ چک)",
    "INSTALLMENT": "اقساط",
}
_RECEIPT_METHOD_CODES = ["CASH", "BANK", "CHECK", "DISCOUNT", "GOODS_COUPON", "VOUCHER", "NETTING", "INSTALLMENT"]
_PAYMENT_METHOD_CODES = ["CASH", "BANK", "CHECK", "DISCOUNT", "CHECK_DISBURSEMENT", "NETTING", "INSTALLMENT"]
# طبقِ درخواستِ صریح («در فرمِ دریافت/پرداخت هم دکمه‌ای باشد که به
# فاکتورهایِ تسویه‌نشده لینک باشد»): مسیرِ معکوسِ همان چیزی که در
# commercial_settlement.py ساخته شد.
_INVOICE_TYPE_BY_DIRECTION = {"RECEIPT": "SALES_INVOICE", "PAYMENT": "PURCHASE_INVOICE"}
_LINK_INVOICE_COLUMNS = ["نوع", "شماره", "موعدِ تسویه", "جمعِ کل", "مانده", "مبلغِ تسویه"]


def _describe_invoice_settlement(direction: str, entries_info: list[tuple], counterparty_label: str) -> str:
    """طبقِ درخواستِ صریح («وقتی مقدارِ تسویه برایِ یک فاکتورِ خاص وارد
    می‌شود، شرحِ پیش‌فرضِ هدر را سیستم ایجاد کند -- مثلاً "پرداخت بابتِ
    تسویه‌یِ قسمتی از فاکتورِ شماره‌یِ .... «نامِ طرفِ‌حساب»"»).
    entries_info: فهرستی از (document_no, remaining_amount, entered_amount)."""
    noun = "دریافت" if direction == "RECEIPT" else "پرداخت"
    is_partial = any(entered < remaining for _no, remaining, entered in entries_info)
    numbers = "، ".join(f"#{numerals.to_persian_digits(str(no))}" for no, _r, _e in entries_info)
    body = f"فاکتورِ شماره‌یِ {numbers}" if len(entries_info) == 1 else f"فاکتورهایِ شماره‌یِ {numbers}"
    extent = "قسمتی از " if is_partial else ""
    # طبقِ باگِ واقعیِ کشف‌شده با تستِ زنده: گزینه‌هایِ کمبویِ طرفِ‌حساب
    # همیشه به‌شکلِ «کد — نام» ساخته می‌شوند؛ بدونِ این جداکردن، شرحِ
    # خودکار به‌جایِ «... — مشتریِ آزمایشی»، «... — 1 — مشتریِ آزمایشی»
    # می‌شد.
    name_only = counterparty_label.rsplit(" — ", 1)[-1].strip() if counterparty_label else ""
    suffix = f" — {name_only}" if name_only else ""
    return f"{noun} بابتِ تسویه‌یِ {extent}{body}{suffix}"
# طبقِ درخواستِ صریح: تهاتر هم مثلِ نقد/بانک/تخفیف/کالابرگ/بن، تفصیلیِ
# احتمالیِ خودش را (از رویِ نگاشتِ تنظیمات) نشان می‌دهد — پس دیگر همیشه از
# دیالوگِ جزئیات معاف نیست؛ اگر برایِ آن معینی تفصیلی/بُعدِ الزامی نداشت،
# _open_details خودش تشخیص می‌دهد و دیالوگِ خالی باز نمی‌کند.
_METHODS_WITHOUT_DETAILS = ()
# روش‌هایی که — وقتی تفصیلیِ ردیفشان از پیش در تنظیمات تخصیص یافته باشد —
# دقیقاً همان رفتارِ نقدی را دارند: دیالوگ اصلاً باز نمی‌شود، خودکار همان
# پیش‌تخصیص اعمال و فوکوس مستقیم رویِ مبلغ می‌رود. طبقِ درخواستِ صریح، بن
# هم به این فهرست اضافه شد — اگر پیش‌تخصیص نداشته باشد، همچنان دیالوگِ خودش
# (با فیلدهایِ سریال/مشخصات) باز می‌شود، این رفتار فقط برایِ حالتِ
# پیش‌تخصیص‌یافته تغییر کرده است.
_MAPPING_ONLY_DETAIL_METHODS = ("CASH", "BANK", "DISCOUNT", "GOODS_COUPON", "VOUCHER", "NETTING")


def _is_mapping_only_method(method: str | None) -> bool:
    """طبقِ آیتمِ ۷: روش‌هایِ سفارشی (کدشان با CUSTOM_ شروع می‌شود) دقیقاً
    مثلِ نقد/بانک/تخفیف/کالابرگ/بن/تهاتر رفتار می‌کنند — فقط مبلغ +
    تفصیلیِ اختیاری."""
    return method in _MAPPING_ONLY_DETAIL_METHODS or (method is not None and method.startswith("CUSTOM_"))
# نوع‌بُعدهایی که تفصیلیِ نقد/بانک معمولاً از رویِ آن‌ها ساخته می‌شوند —
# فقط برایِ برچسبِ فیلد؛ خودِ فهرستِ گزینه‌ها همیشه از رویِ بُعدِ الزامیِ
# واقعیِ همان معینِ نگاشته‌شده گرفته می‌شود (نه این کدها به‌طورِ مستقیم).


class _EnterComboBox(QComboBox):
    """کمبویِ غیرِقابلِ‌ویرایشِ روش — Enter به‌جایِ بازکردنِ popup، سیگنالِ
    enterPressed می‌فرستد تا زنجیره‌یِ ناوبریِ کیبوردیِ ردیف را کنترل کند.

    باگِ ریشه‌ای که باعثِ رفتارِ «بعضی‌وقت‌ها کار می‌کند بعضی‌وقت‌ها نه» می‌شد:
    وقتی popupِ کمبو باز است (مثلاً با کلیک یا فلش‌رو‌به‌پایین)، Enter برایِ
    انتخابِ گزینه‌یِ highlight‌شده و بستنِ خودِ popup به view/popup داخلیِ Qt
    می‌رود، نه به keyPressEventِ همین ویجت — پس enterPressed اصلاً امیت
    نمی‌شد و _open_details هیچ‌وقت اجرا نمی‌شد. حالا با یک eventFilter رویِ
    self.view()، همان Enterِ داخلِ popup هم گرفته و enterPressed امیت
    می‌شود (با singleShot تا بعد از commit‌شدنِ انتخابِ Qt، currentData
    درست خوانده شود)."""

    enterPressed = Signal()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.view().installEventFilter(self)

    def keyPressEvent(self, event) -> None:  # noqa: N802 — نامِ متدِ Qt
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.enterPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 — نامِ متدِ Qt
        if (
            watched is self.view()
            and event.type() == QEvent.KeyPress
            and event.key() in (Qt.Key_Return, Qt.Key_Enter)
        ):
            QTimer.singleShot(0, self.enterPressed.emit)
        return super().eventFilter(watched, event)


# طبقِ درخواستِ صریح: مرکزِ هزینه/پروژه ویژگیِ خودِ رویدادِ مالی‌اند، نه
# طرفِ‌حساب یا روش — همان مقداری که در هدرِ فرم انتخاب شده باید برایِ همه‌ی
# ردیف‌ها به‌کار رود (create_treasury_voucher خودش این را با shared_details
# تضمین می‌کند)؛ پس اگر بُعدِ الزامیِ معینِ یک روش مرکزِ هزینه/پروژه باشد،
# دیالوگِ آن روش دوباره از کاربر نمی‌پرسد.
_HEADER_SHARED_DIMENSION_CODES = (dimensions_service.COST_CENTER_CODE, dimensions_service.PROJECT_CODE)


def _detail_option_label(row) -> str:
    """طبقِ گزارشِ صریح: هرجا فهرستِ تفصیلی فیلتر/جست‌وجو می‌شود، هم کد هم
    نام نشان داده شود (نه فقط نام) — تا تفصیلی‌هایِ هم‌نام یا نزدیک‌به‌هم
    قابلِ‌تشخیص باشند، دقیقاً هم‌الگو با فرمتِ کدِ حساب‌ها در بقیه‌یِ برنامه."""
    full_code = getattr(row, "full_code", "") or getattr(row, "code", "")
    name = getattr(row, "name", None)
    if name and full_code:
        return f"{full_code} — {name}"
    return name or full_code or getattr(row, "code", "")


def _detail_name_only(row) -> str:
    """طبقِ گزارشِ صریح: در شرحِ خودکارِ سند فقط نامِ تفصیلی لازم است، نه
    کدش — کد فقط برایِ تشخیصِ گزینه‌ها در فهرست‌هایِ جست‌وجو لازم است
    (_detail_option_label بالا)، نه در متنِ نهاییِ شرحِ سند."""
    return getattr(row, "name", None) or getattr(row, "full_code", "") or getattr(row, "code", "")


def _leaf_detail_accounts_excluding_cost_center_project(company_id: int) -> list:
    """طبقِ آیتمِ ۸: تفصیلی‌هایِ برگِ شرکت به‌جز مرکزِ هزینه/پروژه — این دو
    بُعد از قبل جداگانه در هدرِ فرم پوشش داده می‌شوند (آیتمِ ۱)، پس نباید
    دوباره در جست‌وجویِ آزادِ روش‌هایِ تخفیف/کالابرگ/بن/تهاتر ظاهر شوند."""
    excluded_type_ids = {
        dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.COST_CENTER_CODE),
        dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.PROJECT_CODE),
    }
    return [
        d
        for d in dimensions_service.list_all_leaf_detail_accounts(company_id)
        if d.dimension_type_id not in excluded_type_ids
    ]


def _resolve_row_detail_source(
    company_id: int,
    mapping_key: str,
    covered_dimension_type_ids: set[int] | None = None,
    header_person_group_id: int | None = None,
) -> tuple[int | None, tuple[int, str] | None, str, list]:
    """منبعِ تفصیلیِ یک ردیف (نقد/بانک/تخفیف/کالابرگ/بن/تهاتر) را مشخص
    می‌کند — به‌ترتیبِ اولویت:

    ۱) تفصیلیِ اختصاصیِ از‌پیش‌تخصیص‌یافته در تنظیماتِ خزانه‌داری (طبقِ
       درخواستِ صریح: «در هر ردیف از نوع سند غیر از کد معین بتوان کد
       تفصیلی خاص هم تخصیص داد») — اگر باشد، دیگر از کاربر پرسیده نمی‌شود.
    ۲) بُعدِ(هایِ) الزامیِ واقعیِ همان معینِ نگاشته‌شده — هم گروهِ شخصیِ
       الزامی (get_required_person_groups_for_account، مثلاً «فقط
       مشتری») هم نوع‌بُعدهایِ الزامیِ دیگر (get_required_dimensions_for_account)،
       دقیقاً همان منطقِ صفحه‌ی صدورِ سند: اگر گروهِ شخصی الزامی باشد،
       فقط اشخاصِ همان گروه؛ به‌علاوه‌یِ هر نوع‌بُعدِ دیگری که الزامی
       باشد (مرکزِ هزینه/پروژه فقط وقتی حذف می‌شوند که هدرِ فرم واقعاً
       پوشششان داده باشد). قبلاً این تابع فقط نوع‌بُعدها را می‌خواند، نه
       گروهِ شخص را — نتیجه این بود که وقتی مثلاً معینِ تخفیف به گروهِ
       «مشتری» محدود شده بود، این محدودیت نادیده گرفته می‌شد و به‌جایِ آن
       فهرستِ آزادِ همه‌یِ تفصیلی‌های شرکت (بندِ ۳) پیشنهاد می‌شد.
       طبقِ گزارشِ صریحِ بعدی: حتی اگر طرفِ‌حسابِ هدر خودش عضوِ همان
       گروهِ الزامی باشد، باز هم این فیلد نمایش داده می‌شود — قبلاً در
       این حالت دیگر چیزی پرسیده نمی‌شد (خودکار همان انتخابِ هدر اعمال
       می‌شد)، ولی نتیجه‌اش این بود که کاربر نمی‌دانست کِی برایِ تخفیف/
       نقد/بانک/… از او تفصیلی پرسیده می‌شود و کِی نه («بعضی‌وقتا
       می‌پرسه، بعضی‌وقتا نه، نمی‌دونم چرا»). حالا همیشه پرسیده می‌شود،
       حتی اگر فقط یک گزینه (همان طرفِ‌حسابِ هدر) در فهرست باشد.
    ۳) اگر معین نه گروهِ شخصیِ الزامی داشته باشد نه هیچ نوع‌بُعدِ دیگری
       (مثلاً تخفیف که هنوز چیزی رویش تنظیم نشده) — به‌جایِ این‌که هیچ‌جا
       نتوان تفصیلی وارد کرد، جستجویِ آزاد رویِ همه‌یِ تفصیلی‌هایِ برگِ
       شرکت پیشنهاد می‌شود («اگر تفصیلی تخصیص ندهیم از سند انتخاب کنیم»).

    خروجی: (account_id, پیش‌تخصیص (id, برچسب) یا None، برچسبِ فیلد، فهرستِ گزینه‌ها)."""
    account_id, preset_detail_id = treasury_service.get_account_mapping_with_detail(company_id, mapping_key)
    if account_id is None:
        return None, None, "", []
    preset, label, options = _resolve_account_detail_options(
        company_id, account_id, preset_detail_id, covered_dimension_type_ids, header_person_group_id
    )
    return account_id, preset, label, options


def _resolve_account_detail_options(
    company_id: int,
    account_id: int,
    preset_detail_id: int | None,
    covered_dimension_type_ids: set[int] | None,
    header_person_group_id: int | None,
) -> tuple[tuple[int, str] | None, str, list]:
    """هسته‌یِ resolveِ تفصیلیِ یک معینِ مشخص — بدونِ خواندنِ مستقیمِ
    account_mappings — تا هم توسطِ _resolve_row_detail_source (حالتِ
    تک‌معینی) و هم _resolve_row_detail_sources (آیتمِ ۹، حالتِ چندمعینی)
    قابلِ‌فراخوانی باشد."""
    if preset_detail_id is not None:
        # طبقِ آیتمِ ۸: حذفِ مرکزِ هزینه/پروژه فقط مالِ جستجویِ آزادِ
        # پایین‌تر (بندِ ۳) است — یک پیش‌تخصیصِ صریحاً تنظیم‌شده در تنظیمات
        # (حتی اگر رویِ مرکزِ هزینه/پروژه باشد) باید همچنان درست resolve
        # و برچسبش نمایش داده شود؛ کاربر آن را عمداً انتخاب کرده، نه از
        # نشتِ جستجویِ آزاد.
        preset_row = next(
            (
                d
                for d in dimensions_service.list_all_leaf_detail_accounts(company_id)
                if d.detail_account_id == preset_detail_id
            ),
            None,
        )
        # طبقِ گزارشِ صریح: این برچسب فقط برایِ متنِ شرحِ خودکارِ سند مصرف
        # می‌شود (نه نمایشِ گزینه‌ها) — پس فقط نام، بدونِ کد.
        preset_label = _detail_name_only(preset_row) if preset_row is not None else ""
        return (preset_detail_id, preset_label), "", []
    required = dimensions_service.get_required_dimensions_for_account(account_id)
    # طبقِ گزارشِ صریحِ نهایی: مرکزِ هزینه/پروژه فقط و همیشه در هدرِ فرم
    # (که دو کمبویِ اختصاصیِ خودش را دارد، همیشه در دسترس) پرسیده می‌شوند —
    # هیچ‌وقت در فهرستِ تفصیلیِ یک ردیف، حتی اگر معینِ همان ردیف این دو
    # بُعد را الزامی کرده باشد و هدر هم آن‌ها را پوشش نداده باشد. قبلاً
    # فقط وقتی هدر «پوشش» می‌داد حذف می‌شدند — نتیجه این بود که برایِ
    # حساب‌هایی که این دو بُعد رویشان تیک خورده (حتی اشتباهاً)، در فهرستِ
    # تفصیلیِ هر ردیف (تخفیف/کالابرگ/بن/تهاتر/...) ظاهر می‌شدند و بینِ
    # تفصیلیِ واقعیِ ردیف قاطی می‌شدند. اگر معینی واقعاً این بُعدها را
    # الزامی کند و هدر پوششش ندهد، ثبتِ سند خودش با خطایِ روشن رد می‌شود
    # (create_journal_entry: «انتخابِ ابعادِ تفصیلیِ الزامی فراموش شده
    # است») — نه سکوت/نشتِ داده.
    other_dims = [r for r in required if r.code not in _HEADER_SHARED_DIMENSION_CODES]
    # طبقِ گزارشِ صریح: تا پیش از این، محدودیتِ گروهِ اشخاص (مثلاً «فقط
    # مشتری») که رویِ معینِ همین روش تنظیم شده بود اصلاً خوانده نمی‌شد —
    # نتیجه این بود که وقتی پیش‌تخصیصی در تنظیمات نبود، به‌جایِ فهرستِ
    # تفصیلی‌هایِ همان معین، فهرستِ کاملِ همه‌ی تفصیلی‌هایِ شرکت (آزاد)
    # پیشنهاد می‌شد. حالا همان منطقِ صفحه‌ی صدورِ سند
    # (journal_entry._MethodRow._refresh_dimension_ui) این‌جا هم تکرار
    # می‌شود: گروهِ شخصیِ الزامی + بقیه‌ی نوع‌بُعدهایِ الزامی، هردو با هم.
    # طبقِ گزارشِ صریح («بعضی‌وقتا تفصیلیِ تخفیف/نقد/بانک/… را نمی‌پرسه،
    # نمی‌دونم چرا»): قبلاً اگر طرفِ‌حسابِ هدر خودش عضوِ همان گروهِ الزامی
    # بود، این ردیف دیگر چیزی نمی‌پرسید (خودکار همان انتخابِ هدر اعمال
    # می‌شد) — همین رفتارِ نامنظم/غیرقابل‌پیش‌بینی گزارش شد. حالا
    # header_person_group_id دیگر گزینه‌ها را حذف نمی‌کند؛ همیشه فهرستِ
    # کاملِ اشخاصِ همان گروه پیشنهاد می‌شود، حتی اگر طرفِ‌حسابِ هدر هم
    # جزوِ همان گروه/گزینه‌ها باشد.
    person_group_ids = [
        g.person_group_id for g in dimensions_service.get_required_person_groups_for_account(account_id)
    ]
    if not person_group_ids and not other_dims:
        if required:
            # همه‌ی بُعدهای الزامی مرکزِ هزینه/پروژه‌اند (هدر پوششان داده) —
            # چیزی نمی‌پرسد، چون آن فیلدها از قبل بالایِ فرم دیده می‌شوند.
            return None, "", []
        # نه گروهِ شخصیِ الزامی نه هیچ نوع‌بُعدی -> جستجویِ آزادِ همه‌ی تفصیلی‌ها
        # (به‌جز مرکزِ هزینه/پروژه، طبقِ آیتمِ ۸ — این‌ها از قبل در هدر پوشش داده می‌شوند)
        return None, "تفصیلی", _leaf_detail_accounts_excluding_cost_center_project(company_id)
    options = []
    labels = []
    if person_group_ids:
        labels.append("تفصیلیِ اشخاص")
        options.extend(
            p for p in dimensions_service.list_active_persons(company_id) if p.person_group_id in person_group_ids
        )
    for dim in other_dims:
        labels.append(dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(dim.code, dim.code))
        options.extend(dim.detail_accounts)
    return None, " / ".join(labels), options


def _resolve_row_detail_sources(
    company_id: int,
    mapping_key: str,
    covered_dimension_type_ids: set[int] | None = None,
    header_person_group_id: int | None = None,
) -> tuple[int | None, tuple[int, str] | None, str, list, dict[int, int]]:
    """طبقِ آیتمِ ۹: نسخه‌یِ چندمعینیِ _resolve_row_detail_source — اگر فقط
    یک معین برایِ این mapping_key تنظیم شده باشد، دقیقاً همان رفتار
    (شاملِ پیش‌تخصیص) بدونِ تغییر اجرا می‌شود. اگر بیش از یک معین تنظیم
    شده باشد، پیش‌تخصیص نادیده گرفته می‌شود و گزینه‌هایِ هرکدام (طبقِ
    همان منطقِ تک‌معینی) با هم union می‌شوند؛ خروجیِ پنجم یک نگاشتِ
    {detail_account_id: account_id} است تا وقتی کاربر یک تفصیلی از
    فهرستِ ترکیبی انتخاب می‌کند، معینِ متناظرش هم معلوم باشد
    (MethodLine.account_id_override)."""
    mapped_accounts = treasury_service.list_mapped_accounts_for_key(company_id, mapping_key)
    if len(mapped_accounts) <= 1:
        account_id, preset, label, options = _resolve_row_detail_source(
            company_id, mapping_key, covered_dimension_type_ids, header_person_group_id
        )
        return account_id, preset, label, options, {}
    combined_options: list = []
    combined_labels: list[str] = []
    account_id_by_detail: dict[int, int] = {}
    for mapped in mapped_accounts:
        _preset, sub_label, sub_options = _resolve_account_detail_options(
            company_id, mapped.account_id, None, covered_dimension_type_ids, header_person_group_id
        )
        if sub_label and sub_label not in combined_labels:
            combined_labels.append(sub_label)
        for option in sub_options:
            account_id_by_detail[option.detail_account_id] = mapped.account_id
        combined_options.extend(sub_options)
    return None, None, " / ".join(combined_labels), combined_options, account_id_by_detail


def _resolve_supplementary_person_detail(
    company_id: int,
    mapping_key: str,
    header_person_group_id: int | None = None,
    header_detail_account_id: int | None = None,
) -> tuple[tuple[int, str] | None, str, list]:
    """طبقِ گزارشِ صریح: روشِ چک (دریافت/پرداخت) و خرجِ چک، برخلافِ نقد/بانک/
    تخفیف/کالابرگ/بن/تهاتر، فیلدِ تخصصیِ خودشان را دارند (چندچکیِ دریافتی،
    حسابِ بانکیِ صادرکننده، چکِ دریافتیِ خرج‌شونده) و از _resolve_row_detail_source
    استفاده نمی‌کنند — نتیجه این بود که اگر معینِ نگاشته‌شده‌یِ همان روش به
    یک گروهِ شخص محدود شده بود (مثلاً «اسناد دریافتنی نزدِ صندوق» که فقط
    مشتری/تامین‌کننده مجازند)، این محدودیت هیچ‌جا خوانده نمی‌شد و ثبتِ سند
    با خطایِ «انتخابِ یک تفصیلیِ اشخاص از گروهِ مجاز الزامی است» رد می‌شد.
    این تابع، مستقل از فیلدهایِ تخصصیِ همان دیالوگ‌ها، فقط همین محدودیتِ
    گروهِ شخص را (اگر باشد) به‌عنوانِ یک فیلدِ *تکمیلی* برمی‌گرداند — برخلافِ
    _resolve_row_detail_source، اگر هیچ گروهِ شخصی الزامی نباشد چیزی
    پیشنهاد نمی‌دهد (فهرستِ آزاد این‌جا معنا ندارد، چون این فیلدِ اصلیِ
    ردیف نیست).

    طبقِ گزارشِ صریحِ تازه‌ی «قسمتِ دریافتِ چک»: اگر فراخوان بدونِ
    header_detail_account_id تماس بگیرد (بقیه‌ی مصرف‌کننده‌ها، مثلِ
    خرجِ چک)، رفتار همان قبلی می‌ماند — همیشه فهرستِ انتخاب نمایش داده
    می‌شود، حتی اگر طرفِ‌حسابِ هدر عضوِ همان گروه باشد. اما وقتی فراخوان
    (فقط _CheckEntryDialog) این آرگومان را می‌دهد: اگر طرفِ‌حسابِ هدر
    خودش عضوِ همان گروهِ الزامی باشد، همان طرفِ‌حساب به‌عنوانِ پیش‌فرضِ
    قطعی برگردانده می‌شود (دیگر دوباره پرسیده نمی‌شود)؛ فقط وقتی گروهِ
    الزامیِ این معین با گروهِ طرفِ‌حسابِ هدر فرق داشته باشد، فهرستِ آزادِ
    انتخاب (از همان گروهِ الزامی) نمایش داده می‌شود."""
    account_id, preset_detail_id = treasury_service.get_account_mapping_with_detail(company_id, mapping_key)
    if account_id is None:
        return None, "", []
    person_group_ids = [
        g.person_group_id for g in dimensions_service.get_required_person_groups_for_account(account_id)
    ]
    if not person_group_ids:
        return None, "", []
    if preset_detail_id is not None:
        preset_row = next(
            (p for p in dimensions_service.list_active_persons(company_id) if p.detail_account_id == preset_detail_id),
            None,
        )
        # طبقِ گزارشِ صریح: این برچسب فقط در متنِ شرحِ خودکارِ سند مصرف
        # می‌شود — پس فقط نام، بدونِ کد.
        preset_label = _detail_name_only(preset_row) if preset_row is not None else ""
        return (preset_detail_id, preset_label), "", []
    if header_detail_account_id is not None and header_person_group_id in person_group_ids:
        header_row = next(
            (
                p
                for p in dimensions_service.list_active_persons(company_id)
                if p.detail_account_id == header_detail_account_id
            ),
            None,
        )
        header_label = _detail_name_only(header_row) if header_row is not None else ""
        return (header_detail_account_id, header_label), "", []
    persons = [p for p in dimensions_service.list_active_persons(company_id) if p.person_group_id in person_group_ids]
    return None, "تفصیلیِ اشخاص", persons


class _MethodDetailsDialog(QDialog):
    """جزئیاتِ مخصوصِ روشِ انتخاب‌شده‌یِ یک ردیف — نقد/بانک/تخفیف/کالابرگ:
    تفصیلیِ سطحِ آخرِ حسابِ معینِ نگاشته‌شده؛ خرجِ چک: کدام چکِ دریافتی؛
    بن: سریال+مشخصات. چک (هم دریافت هم پرداخت) دیگر این‌جا نیست — دیالوگِ
    چندچکیِ _CheckEntryDialog هردو جهت را پوشش می‌دهد."""

    def __init__(
        self,
        direction: str,
        method: str,
        company_id: int,
        current: dict,
        parent=None,
        covered_dimension_type_ids: set[int] | None = None,
        header_person_group_id: int | None = None,
        decimal_places: int = 0,
        counterparty_detail_account_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"جزئیاتِ ردیفِ {_METHOD_LABELS.get(method, method)}")
        layout = QFormLayout(self)
        self._decimal_places = decimal_places

        self.detail_combo: QComboBox | None = None
        self.preset_detail_id: int | None = None
        self.preset_detail_label: str = ""
        self.received_check_table: QTableWidget | None = None
        self.voucher_serial_field: QLineEdit | None = None
        self.voucher_detail_field: QLineEdit | None = None
        self.person_detail_combo: QComboBox | None = None
        self.preset_person_detail_id: int | None = None
        self.preset_person_detail_label: str = ""
        self.installment_document_combo: QComboBox | None = None
        self.installment_count_field: _AmountField | None = None
        self.installment_first_due_field: JalaliDateEdit | None = None
        self._detail_names: dict[int, str] = {}
        self._person_detail_names: dict[int, str] = {}
        # طبقِ آیتمِ ۹: اگر چند معین برایِ این mapping_key تنظیم شده باشد،
        # این نگاشت مشخص می‌کند تفصیلیِ انتخاب‌شده متعلق به کدام معین است.
        self._account_id_by_detail: dict[int, int] = {}

        if _is_mapping_only_method(method):
            mapping_key = f"{direction}_{method}"
            _account_id, preset, label, options, self._account_id_by_detail = _resolve_row_detail_sources(
                company_id, mapping_key, covered_dimension_type_ids, header_person_group_id
            )
            if preset is not None:
                self.preset_detail_id, self.preset_detail_label = preset
            elif options:
                self._detail_names = {o.detail_account_id: _detail_name_only(o) for o in options}
                self.detail_combo = _make_searchable_combo(
                    [(o.detail_account_id, _detail_option_label(o)) for o in options]
                )
                if current.get("detail_account_id") is not None:
                    index = self.detail_combo.findData(current["detail_account_id"])
                    if index >= 0:
                        self.detail_combo.setCurrentIndex(index)
                layout.addRow(label or "تفصیلی", self.detail_combo)
        if method == "INSTALLMENT":
            # طبقِ درخواستِ صریح («روشِ دریافت/پرداختِ اقساطی»): فقط
            # فاکتورهایِ ثبت‌شده‌یِ همان طرفِ‌حساب (و همان جهت -- فروش
            # برایِ دریافت، خرید برایِ پرداخت) که هنوز کاملاً تسویه
            # نشده‌اند قابلِ‌انتخاب‌اند.
            invoice_type = "SALES_INVOICE" if direction == "RECEIPT" else "PURCHASE_INVOICE"
            unsettled = settlements_service.list_unsettled_invoices(company_id, document_type_code=invoice_type)
            options = []
            for status in unsettled:
                try:
                    doc, _lines = documents_service.get_document(status.document_id, company_id)
                except ValueError:
                    continue
                if counterparty_detail_account_id is not None and doc.counterparty_detail_account_id != counterparty_detail_account_id:
                    continue
                label = f"فاکتورِ #{numerals.to_persian_digits(str(doc.document_no))} — مانده: {numerals.format_money(status.remaining_amount, decimal_places)}"
                options.append((status.document_id, label))
            self.installment_document_combo = _make_searchable_combo(options)
            if current.get("installment_document_id") is not None:
                index = self.installment_document_combo.findData(current["installment_document_id"])
                if index >= 0:
                    self.installment_document_combo.setCurrentIndex(index)
            layout.addRow("فاکتورِ موردِنظر", self.installment_document_combo)

            self.installment_count_field = _AmountField()
            self.installment_count_field.setDecimals(0)
            self.installment_count_field.setValue(current.get("installment_count") or 3)
            layout.addRow("تعدادِ اقساط", self.installment_count_field)

            self.installment_first_due_field = JalaliDateEdit()
            self.installment_first_due_field.setDate(
                current.get("installment_first_due_date") or (datetime.date.today() + datetime.timedelta(days=30))
            )
            layout.addRow("سررسیدِ اولین قسط", self.installment_first_due_field)
        if method == "VOUCHER":
            self.voucher_serial_field = PersianDigitLineEdit(current.get("voucher_serial") or "")
            layout.addRow("سریالِ بن", self.voucher_serial_field)
            self.voucher_detail_field = QLineEdit(current.get("voucher_detail") or "")
            layout.addRow("مشخصاتِ بن", self.voucher_detail_field)
            if self.detail_combo is not None:
                self.detail_combo.lineEdit().returnPressed.connect(self.voucher_serial_field.setFocus)
            self.voucher_serial_field.returnPressed.connect(self.voucher_detail_field.setFocus)
            self.voucher_detail_field.returnPressed.connect(self.accept)
        elif self.detail_combo is not None:
            self.detail_combo.lineEdit().returnPressed.connect(self.accept)
        if method == "CHECK_DISBURSEMENT":
            # طبقِ درخواستِ صریح: «چند چک انتخاب کنیم، فیلتر روی تاریخ و
            # شماره‌یِ چک و ستون‌هایِ مختلف بگذاریم، و بر اساسِ ستون‌ها/
            # فیلدهایِ چک جست‌وجو کنیم» — به‌جایِ فهرستِ سادهٔ متنی، جدولِ
            # چک‌مارک‌دارِ چندانتخابیِ واقعی با ستون‌هایِ جداگانه، یک نوارِ
            # جست‌وجویِ زنده (شماره‌یِ چک/بانک/صادرکننده)، و یک فیلترِ اختیاریِ
            # بازه‌یِ سررسید. مبلغِ ردیف خودکار از جمعِ چک‌هایِ تیک‌خورده پر
            # می‌شود.
            check_container = QWidget()
            check_container_layout = QVBoxLayout(check_container)
            check_container_layout.setContentsMargins(0, 0, 0, 0)
            check_container_layout.setSpacing(4)

            filter_row = QHBoxLayout()
            self.check_search_field = QLineEdit()
            self.check_search_field.setPlaceholderText("جست‌وجو در شماره‌یِ چک/بانک/صادرکننده…")
            filter_row.addWidget(self.check_search_field, stretch=1)
            self.check_due_filter_enabled = QCheckBox("فیلترِ بازه‌یِ سررسید")
            filter_row.addWidget(self.check_due_filter_enabled)
            filter_row.addWidget(QLabel("از"))
            self.check_due_from_field = JalaliDateEdit()
            self.check_due_from_field.setEnabled(False)
            filter_row.addWidget(self.check_due_from_field)
            filter_row.addWidget(QLabel("تا"))
            self.check_due_to_field = JalaliDateEdit()
            self.check_due_to_field.setEnabled(False)
            filter_row.addWidget(self.check_due_to_field)
            check_container_layout.addLayout(filter_row)

            self.received_check_table = QTableWidget(0, 6)
            self.received_check_table.setHorizontalHeaderLabels(
                ["", "شماره‌یِ چک", "بانک", "صادرکننده", "مبلغ", "سررسید"]
            )
            self.received_check_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.received_check_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.received_check_table.verticalHeader().setVisible(False)
            self.received_check_table.setSortingEnabled(True)
            self.received_check_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
            self.received_check_table.setColumnWidth(0, 26)
            self.received_check_table.setMinimumHeight(200)
            check_container_layout.addWidget(self.received_check_table)

            eligible_checks = treasury_service.list_received_checks(company_id, status_codes=["IN_HAND", "DEPOSITED"])
            current_ids = set(
                current.get("received_check_ids")
                or ([current["received_check_id"]] if current.get("received_check_id") is not None else [])
            )
            self.received_check_table.setSortingEnabled(False)
            self.received_check_table.setRowCount(len(eligible_checks))
            for row_index, c in enumerate(eligible_checks):
                check_item = QTableWidgetItem()
                check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                check_item.setCheckState(Qt.Checked if c.received_check_id in current_ids else Qt.Unchecked)
                check_item.setData(Qt.UserRole, (c.received_check_id, c.amount))
                search_text = f"{c.check_no} {c.drawee_bank_name or ''} {c.drawer_name or ''}".lower()
                check_item.setData(Qt.UserRole + 1, search_text)
                check_item.setData(Qt.UserRole + 2, c.due_date)
                self.received_check_table.setItem(row_index, 0, check_item)
                values = [
                    c.check_no,
                    c.drawee_bank_name or "—",
                    c.drawer_name or "—",
                    numerals.format_money(c.amount, self._decimal_places),
                    numerals.format_jalali_date(c.due_date),
                ]
                for col_index, value in enumerate(values, start=1):
                    cell_item = QTableWidgetItem(value)
                    if col_index == 4:
                        cell_item.setData(Qt.InitialSortOrderRole, float(c.amount))
                        cell_item.setData(Qt.UserRole, float(c.amount))
                    if col_index == 5:
                        cell_item.setData(Qt.UserRole, c.due_date.toordinal())
                    self.received_check_table.setItem(row_index, col_index, cell_item)
            self.received_check_table.setSortingEnabled(True)

            self.check_search_field.textChanged.connect(self._apply_check_disbursement_filter)
            self.check_due_filter_enabled.toggled.connect(self.check_due_from_field.setEnabled)
            self.check_due_filter_enabled.toggled.connect(self.check_due_to_field.setEnabled)
            self.check_due_filter_enabled.toggled.connect(self._apply_check_disbursement_filter)
            self.check_due_from_field.editingFinished.connect(self._apply_check_disbursement_filter)
            self.check_due_to_field.editingFinished.connect(self._apply_check_disbursement_filter)

            layout.addRow("چک‌هایِ دریافتیِ خرج‌شونده", check_container)

        if method == "CHECK_DISBURSEMENT":
            # طبقِ گزارشِ صریح: خرجِ چک فیلدِ تخصصیِ خودش را دارد (چکِ
            # دریافتیِ خرج‌شونده) که تفصیلیِ اصلیِ ردیف است — اما اگر معینِ
            # نگاشته‌شده‌یِ همین روش، جدا از آن، به یک گروهِ شخص هم محدود
            # شده باشد (مثلاً «فقط تامین‌کننده»)، این محدودیت باید همین‌جا
            # هم به‌عنوانِ یک فیلدِ تکمیلی پرسیده شود؛ وگرنه ثبتِ سند در
            # همان اعتبارسنجیِ نهاییِ journal_entries رد می‌شود، بدونِ
            # این‌که کاربر جایی برایِ واردکردنش داشته باشد.
            preset, person_label, persons = _resolve_supplementary_person_detail(
                company_id, f"{direction}_{method}", header_person_group_id
            )
            if preset is not None:
                self.preset_person_detail_id, self.preset_person_detail_label = preset
            elif persons:
                self._person_detail_names = {p.detail_account_id: _detail_name_only(p) for p in persons}
                self.person_detail_combo = _make_searchable_combo(
                    [(p.detail_account_id, _detail_option_label(p)) for p in persons]
                )
                if current.get("person_detail_account_id") is not None:
                    index = self.person_detail_combo.findData(current["person_detail_account_id"])
                    if index >= 0:
                        self.person_detail_combo.setCurrentIndex(index)
                layout.addRow(person_label or "تفصیلیِ اشخاص", self.person_detail_combo)

        if method == "CHECK_DISBURSEMENT":
            self.resize(680, 440)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("تایید")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        # طبقِ بررسیِ عملی: setAutoDefault(False) به‌تنهایی کافی نیست —
        # QDialogButtonBox با هر show() دوباره دکمه‌یِ نقشِ AcceptRole را
        # default (isDefault=True) می‌کند، جدا از پرچمِ autoDefault. برایِ
        # همین Enterِ زده‌شده در هر فیلدی (حتی اگر خودِ فیلد returnPressed
        # را برایِ جابه‌جاییِ فوکوس مصرف کرده باشد) از keyPressEvent خودِ
        # QDialog هم عبور می‌کند و دکمه را دوباره کلیک می‌کند. جلوگیریِ
        # واقعی در keyPressEvent زیر انجام شده؛ این دو خط هم به‌عنوانِ
        # لایه‌یِ دومِ دفاعی نگه داشته می‌شوند.
        buttons.button(QDialogButtonBox.Ok).setAutoDefault(False)
        buttons.button(QDialogButtonBox.Cancel).setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def keyPressEvent(self, event) -> None:
        # جلوگیریِ واقعی از باگِ autoDefault: چون همه‌یِ فیلدهایِ این دیالوگ
        # زنجیره‌یِ Enterِ خودشان را دارند، دیگر نیازی نیست QDialog با
        # دیدنِ Enter دوباره دکمه‌یِ پیش‌فرض را کلیک کند.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def _apply_check_disbursement_filter(self) -> None:
        """طبقِ درخواستِ صریح: جست‌وجویِ زنده در شماره‌یِ چک/بانک/صادرکننده +
        فیلترِ اختیاریِ بازه‌یِ سررسید — فقط ردیف‌هایِ منطبق دیده می‌شوند؛
        وضعیتِ تیک‌خورده‌بودنِ ردیف‌هایِ پنهان‌شده هم دست‌نخورده می‌ماند."""
        if self.received_check_table is None:
            return
        query = self.check_search_field.text().strip().lower()
        use_due_filter = self.check_due_filter_enabled.isChecked()
        due_from = self.check_due_from_field.date() if use_due_filter else None
        due_to = self.check_due_to_field.date() if use_due_filter else None
        for row_index in range(self.received_check_table.rowCount()):
            item = self.received_check_table.item(row_index, 0)
            visible = True
            if query and query not in (item.data(Qt.UserRole + 1) or ""):
                visible = False
            if visible and use_due_filter:
                due_date = item.data(Qt.UserRole + 2)
                if due_date is not None:
                    if due_from is not None and due_date < due_from:
                        visible = False
                    if due_to is not None and due_date > due_to:
                        visible = False
            self.received_check_table.setRowHidden(row_index, not visible)

    def result_data(self) -> dict:
        data: dict = {}
        if self.preset_detail_id is not None:
            data["detail_account_id"] = self.preset_detail_id
            data["detail_account_label"] = self.preset_detail_label
        elif self.detail_combo is not None:
            data["detail_account_id"] = self.detail_combo.currentData()
            # طبقِ گزارشِ صریح: این برچسب فقط در متنِ شرحِ خودکارِ سند مصرف
            # می‌شود — پس فقط نام، بدونِ کد.
            data["detail_account_label"] = self._detail_names.get(
                data["detail_account_id"], self.detail_combo.currentText()
            )
            # طبقِ آیتمِ ۹: اگر تفصیلیِ انتخاب‌شده از فهرستِ ترکیبیِ چندمعینی
            # آمده باشد، معینِ متناظرش هم صریحاً به MethodLine منتقل می‌شود
            # (به‌جایِ resolveِ خودکار که در حالتِ چندمعینی مبهم است).
            override_account_id = self._account_id_by_detail.get(data["detail_account_id"])
            if override_account_id is not None:
                data["account_id_override"] = override_account_id
        if self.received_check_table is not None:
            selected_ids: list[int] = []
            total = decimal.Decimal(0)
            for i in range(self.received_check_table.rowCount()):
                item = self.received_check_table.item(i, 0)
                if item.checkState() == Qt.Checked:
                    received_check_id, amount = item.data(Qt.UserRole)
                    selected_ids.append(received_check_id)
                    total += amount
            if selected_ids:
                data["received_check_ids"] = selected_ids
                data["check_amount"] = total
        if self.voucher_serial_field is not None:
            data["voucher_serial"] = self.voucher_serial_field.text().strip()
        if self.voucher_detail_field is not None:
            data["voucher_detail"] = self.voucher_detail_field.text().strip()
        if self.preset_person_detail_id is not None:
            data["person_detail_account_id"] = self.preset_person_detail_id
            data["person_detail_account_label"] = self.preset_person_detail_label
        elif self.person_detail_combo is not None:
            data["person_detail_account_id"] = self.person_detail_combo.currentData()
            data["person_detail_account_label"] = self._person_detail_names.get(
                data["person_detail_account_id"], self.person_detail_combo.currentText()
            )
        if self.installment_document_combo is not None:
            data["installment_document_id"] = self.installment_document_combo.currentData()
            data["installment_count"] = int(self.installment_count_field.value())
            data["installment_first_due_date"] = self.installment_first_due_field.date()
        return data


_CHECK_ENTRY_COLUMNS = ["شماره‌یِ چک", "بانک", "مبلغ", "صاحبِ حساب"]


class _CheckEntryDialog(LayoutEditMixin, QDialog):
    """واردکردنِ چند چک در یک ردیف — با «تایید» جمعِ مبلغِ همه‌یِ چک‌ها به
    ردیف منتقل می‌شود. برایِ دریافت: سریال/شماره/شبا/بانک/شماره‌حساب/مبلغ/
    نامِ صاحبِ‌حساب/کدِملی/تلفن. طبقِ درخواستِ صریح، برایِ پرداخت فقط
    سریال/شماره‌چک/شماره‌یِ صیادی/مبلغ/سررسید پرسیده می‌شود — حسابِ بانکیِ
    صادرکننده یک‌بار برایِ کلِ ردیف انتخاب می‌شود و اطلاعاتِ گیرنده خودکار
    از طرفِ‌حسابِ بالایِ فرم می‌آید."""

    def __init__(
        self,
        company_id: int,
        current_checks: list[dict],
        parent=None,
        mapping_key: str = "RECEIPT_CHECK",
        current_person_detail_id: int | None = None,
        header_person_group_id: int | None = None,
        header_counterparty_detail_id: int | None = None,
        direction: str = "RECEIPT",
        current_checkbook_id: int | None = None,
        current_bank_account_detail_id: int | None = None,
        decimal_places: int = 0,
        header_payee_info: tuple[str, str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._direction = direction
        self._decimal_places = decimal_places
        self.setWindowTitle("چک‌هایِ دریافتی" if direction == "RECEIPT" else "چک‌هایِ پرداختی")
        self.setMinimumWidth(620)
        # طبقِ درخواستِ صریح («فضایِ بیشتر برایِ فهرستِ چک‌ها»): ارتفاعِ
        # پیش‌فرضِ دیالوگ بزرگ‌تر تا stretchِ جدول (پایین‌تر) واقعاً فضا
        # داشته باشد.
        self.resize(700, 760)
        outer = QVBoxLayout(self)
        self._checks: list[dict] = list(current_checks or [])
        self._editing_index: int | None = None
        # طبقِ اصلاحِ آیتم‌هایِ ۳/۴: کمبوهایِ پیش‌از-جدولِ‌چک (صندوق/دسته‌چک/
        # حسابِ بانکیِ صادرکننده/تفصیلیِ شخص) هرکدام هم جست‌وجوپذیر شدند
        # (به‌جایِ QComboBoxِ ساده) هم به زنجیره‌یِ Enterِ زیر تا اولین
        # فیلدِ جدولِ چک (سریال) وصل می‌شوند.
        pre_grid_focus_chain: list[QComboBox] = []

        # طبقِ درخواستِ صریح: «پرداخت چند چکه هم باشه» — برایِ پرداخت، پیش از
        # فیلدهایِ تک‌تکِ چک‌ها، دسته‌چک (اختیاری، برایِ شماره‌گذاریِ خودکار)
        # و حسابِ بانکیِ صادرکننده (الزامی) یک‌بار برایِ کلِ ردیف انتخاب
        # می‌شوند — همان دو فیلدی که قبلاً فقط در حالتِ تک‌چکی وجود داشتند.
        self.checkbook_combo: QComboBox | None = None
        self.issuing_bank_combo: QComboBox | None = None
        self.fund_combo: QComboBox | None = None
        if direction == "RECEIPT":
            # طبقِ درخواستِ صریح: پیش‌نیازِ زنجیره‌یِ مراحلِ چرخه‌یِ چک —
            # هرچکِ دریافتی از همین لحظه باید بداند نزدِ کدام صندوقِ مشخص
            # است (هم‌الگو با حسابِ بانکیِ صادرکننده در پرداخت).
            fund_form = QFormLayout()
            cash_box_type_id = dimensions_service.get_specialized_dimension_type_id(
                company_id, dimensions_service.CASH_BOX_CODE
            )
            fund_options = dimensions_service.list_leaf_detail_accounts(company_id, cash_box_type_id)
            if fund_options:
                self.fund_combo = _make_searchable_combo(
                    [(option.detail_account_id, option.name or option.code) for option in fund_options]
                )
                fund_form.addRow("صندوقِ محلِ دریافت", self.fund_combo)
                outer.addLayout(fund_form)
                pre_grid_focus_chain.append(self.fund_combo)
        if direction == "PAYMENT":
            issuing_form = QFormLayout()
            checkbook_options: list[tuple[int | None, str]] = [(None, "(بدونِ دسته‌چک — شماره‌یِ دستی)")]
            checkbook_options.extend(
                (
                    checkbook.checkbook_id,
                    f"{checkbook.bank_account_label} "
                    f"({numerals.to_persian_digits(str(checkbook.next_no))}–{numerals.to_persian_digits(str(checkbook.end_no))})",
                )
                for checkbook in treasury_service.list_checkbooks(company_id)
                if checkbook.is_active and checkbook.next_no <= checkbook.end_no
            )
            self.checkbook_combo = _make_searchable_combo(checkbook_options)
            if current_checkbook_id is not None:
                index = self.checkbook_combo.findData(current_checkbook_id)
                if index >= 0:
                    self.checkbook_combo.setCurrentIndex(index)
            issuing_form.addRow("دسته‌چک", self.checkbook_combo)
            pre_grid_focus_chain.append(self.checkbook_combo)

            bank_account_type_id = dimensions_service.get_specialized_dimension_type_id(
                company_id, dimensions_service.BANK_ACCOUNT_CODE
            )
            self.issuing_bank_combo = _make_searchable_combo(
                [
                    (option.detail_account_id, option.name or option.code)
                    for option in dimensions_service.list_leaf_detail_accounts(company_id, bank_account_type_id)
                ]
            )
            if current_bank_account_detail_id is not None:
                index = self.issuing_bank_combo.findData(current_bank_account_detail_id)
                if index >= 0:
                    self.issuing_bank_combo.setCurrentIndex(index)
            issuing_form.addRow("حسابِ بانکیِ صادرکننده", self.issuing_bank_combo)
            outer.addLayout(issuing_form)
            pre_grid_focus_chain.append(self.issuing_bank_combo)

            # طبقِ درخواستِ صریح: فرمِ چکِ پرداختی دیگر نامِ/کدِملی/تلفنِ
            # گیرنده را از کاربر نمی‌پرسد — این‌ها همان طرفِ‌حسابِ بالایِ
            # فرمِ سند هستند و خودکار همین‌جا (فقط نمایشی) آورده می‌شوند.
            payee_name, payee_national_id, payee_phone = header_payee_info or ("", "", "")
            payee_info_label = QLabel(
                f"گیرنده: {payee_name or '—'}    —    کدِ ملی: {payee_national_id or '—'}    —    تلفن: {payee_phone or '—'}"
            )
            payee_info_label.setObjectName("sectionHint")
            outer.addWidget(payee_info_label)

        # طبقِ باگ‌فیکسِ گزارش‌شده: اگر معینِ نگاشته‌شده‌یِ همین روش (مثلاً
        # «اسناد دریافتنی نزدِ صندوق») به یک گروهِ شخص محدود شده باشد
        # (فقط مشتری/تامین‌کننده)، این محدودیت باید همین‌جا هم پرسیده شود
        # — وگرنه ثبتِ سند در اعتبارسنجیِ نهایی رد می‌شود بدونِ این‌که
        # کاربر جایی برایِ واردکردنش داشته باشد. طبقِ گزارشِ صریحِ تازه
        # (مخصوصِ خودِ چک): اگر طرفِ‌حسابِ هدر عضوِ همان گروهِ الزامی باشد،
        # دیگر دوباره پرسیده نمی‌شود — همان طرفِ‌حسابِ هدر به‌عنوانِ
        # تفصیلیِ چک هم در نظر گرفته می‌شود؛ فقط وقتی گروهِ الزامیِ این
        # معین با گروهِ طرفِ‌حسابِ هدر فرق داشته باشد، فهرستِ آزادِ انتخاب
        # (از همان گروهِ الزامی) نمایش داده می‌شود.
        self.person_detail_combo: QComboBox | None = None
        self.preset_person_detail_id: int | None = None
        self.preset_person_detail_label: str = ""
        self._person_detail_names: dict[int, str] = {}
        preset, person_label, persons = _resolve_supplementary_person_detail(
            company_id, mapping_key, header_person_group_id, header_counterparty_detail_id
        )
        if preset is not None:
            self.preset_person_detail_id, self.preset_person_detail_label = preset
        elif persons:
            person_form = QFormLayout()
            self._person_detail_names = {p.detail_account_id: _detail_name_only(p) for p in persons}
            self.person_detail_combo = _make_searchable_combo(
                [(p.detail_account_id, _detail_option_label(p)) for p in persons]
            )
            if current_person_detail_id is not None:
                index = self.person_detail_combo.findData(current_person_detail_id)
                if index >= 0:
                    self.person_detail_combo.setCurrentIndex(index)
            person_form.addRow(person_label or "تفصیلیِ اشخاص", self.person_detail_combo)
            outer.addLayout(person_form)
            pre_grid_focus_chain.append(self.person_detail_combo)

        self.serial_field = PersianDigitLineEdit()
        self.no_field = PersianDigitLineEdit()
        self.iban_field = PersianDigitLineEdit()
        bank_options: list[tuple[int | None, str]] = [(None, "—")]
        bank_options.extend((bank.bank_id, bank.name) for bank in treasury_service.list_banks(company_id, active_only=True))
        self.bank_combo = _make_searchable_combo(bank_options)
        self.account_no_field = PersianDigitLineEdit()
        self.amount_field = _AmountField()
        self.amount_field.setDecimals(self._decimal_places)
        self.due_field = JalaliDateEdit("سررسید")
        self.due_field.setDate(datetime.date.today())
        self.owner_field = QLineEdit()
        self.national_id_field = PersianDigitLineEdit()
        self.phone_field = PersianDigitLineEdit()
        # طبقِ درخواستِ صریحِ آیتمِ ۳: شماره‌یِ صیادیِ چکِ پرداختی — شناسه‌یِ
        # ۱۶رقمیِ چاپ‌شده رویِ چک، مستقل از شماره‌یِ شبا.
        self.sayad_field = PersianDigitLineEdit()

        if direction == "PAYMENT":
            payee_name, payee_national_id, payee_phone = header_payee_info or ("", "", "")
            self.owner_field.setText(payee_name)
            self.national_id_field.setText(payee_national_id)
            self.phone_field.setText(payee_phone)

        person_word = "صاحبِ حساب" if direction == "RECEIPT" else "گیرنده"
        no_field_label = "شماره‌یِ چک" if direction == "RECEIPT" else "شماره‌یِ چک (خالی = خودکار از دسته‌چک)"
        if direction == "PAYMENT":
            # طبقِ درخواستِ صریحِ آیتمِ ۳: فرمِ چکِ پرداختی فقط همین پنج
            # فیلد را می‌پرسد — شبا/بانکِ گیرنده/شماره‌حسابِ گیرنده معنی
            # ندارند (خودمان صادرکننده‌ایم)، و نام/کدِملی/تلفنِ گیرنده هم
            # بالاتر خودکار از طرفِ‌حسابِ سند آمد (غیرِقابلِ‌ویرایش این‌جا).
            rows = [
                ("سریالِ چک", self.serial_field),
                (no_field_label, self.no_field),
                ("شماره‌یِ صیادی", self.sayad_field),
                ("مبلغ", self.amount_field),
                ("سررسید", self.due_field),
            ]
        else:
            rows = [
                ("سریالِ چک", self.serial_field),
                (no_field_label, self.no_field),
                ("شماره‌یِ شبا", self.iban_field),
                ("بانک", self.bank_combo),
                ("شماره‌یِ حساب", self.account_no_field),
                ("مبلغ", self.amount_field),
                ("سررسید", self.due_field),
                (f"نامِ {person_word}", self.owner_field),
                (f"کدِ ملیِ {person_word}", self.national_id_field),
                (f"تلفنِ {person_word}", self.phone_field),
            ]

        # طبقِ اصلاحِ آیتمِ ۳: کمبوهایِ پیش‌از-جدول (صندوق/دسته‌چک/حسابِ
        # بانکیِ صادرکننده/تفصیلیِ شخص — هرکدام موجود باشند) با Enter به
        # همدیگر و در آخر به اولین فیلدِ جدولِ چک (سریال) وصل می‌شوند.
        for combo, next_combo in zip(pre_grid_focus_chain, pre_grid_focus_chain[1:]):
            combo.lineEdit().returnPressed.connect(next_combo.setFocus)
        if pre_grid_focus_chain:
            pre_grid_focus_chain[-1].lineEdit().returnPressed.connect(self.serial_field.setFocus)

        # طبقِ درخواستِ صریح: با زدنِ Enter در هر فیلدِ نمایش‌داده‌شده، به
        # فیلدِ بعدی برود؛ Enterِ فیلدِ آخر همان کاری را می‌کند که «+
        # افزودن» می‌کند — فهرستِ فیلدها بستگی به جهت (rows بالا) دارد.
        field_widgets = [widget for _label, widget in rows]
        for widget, next_widget in zip(field_widgets, field_widgets[1:]):
            source = widget.lineEdit().returnPressed if isinstance(widget, QComboBox) else widget.returnPressed
            source.connect(next_widget.setFocus)
        last_widget = field_widgets[-1]
        last_signal = last_widget.lineEdit().returnPressed if isinstance(last_widget, QComboBox) else last_widget.returnPressed
        last_signal.connect(self._add_current)

        # طبقِ چرخشِ عمومیِ فرم‌ها به FieldGrid: جایگزینِ ریاضیِ دستیِ
        # row_index // 2 با کمکِ مشترک — همان rows بالا، بدونِ تغییرِ
        # ترتیب یا زنجیره‌یِ Enterِ بالاتر (که مستقل از این گریدِ بصری،
        # مستقیماً از rows/field_widgets ساخته شده). کلیدِ هر FieldSpec
        # ایندکسِ رویِ rows است چون این دیالوگ در هر بار بازشدن دوباره
        # ساخته می‌شود و برچسب‌ها بینِ RECEIPT/PAYMENT فرق دارند.
        self.fields_grid = FieldGrid(
            [FieldSpec(f"field_{index}", label, widget, span=1) for index, (label, widget) in enumerate(rows)],
            columns=2,
        )
        outer.addWidget(self.fields_grid)
        self.register_field_grids(f"treasury_check_entry_{direction.lower()}", [self.fields_grid])

        self.add_button = QPushButton("➕")
        self.add_button.setObjectName("iconButton")
        self.add_button.setFixedWidth(48)
        self.add_button.setToolTip("افزودنِ این چک به فهرست")
        self.add_button.clicked.connect(self._add_current)
        outer.addWidget(self.add_button)

        # طبقِ اصلاحِ آیتمِ ۳: چون فرمِ پرداخت دیگر «بانک» نمی‌پرسد (حسابِ
        # بانکیِ صادرکننده یک‌بار برایِ کلِ ردیف انتخاب می‌شود)، آن ستون
        # برایِ پرداخت بجایش «شماره‌یِ صیادی» را نشان می‌دهد.
        columns = (
            ["شماره‌یِ چک", "شماره‌یِ صیادی", "مبلغ", "گیرنده"]
            if direction == "PAYMENT"
            else _CHECK_ENTRY_COLUMNS
        )
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        # طبقِ درخواستِ صریح: دابل‌کلیک حالا ویرایش می‌کند (نه حذف) — حذف
        # فقط با دکمه‌یِ مشخصِ زیرِ جدول انجام می‌شود.
        self.table.cellDoubleClicked.connect(self._edit_row)
        # طبقِ درخواستِ صریح: فضایِ بیشتر برایِ فهرستِ چک‌ها.
        self.table.setMinimumHeight(220)
        outer.addWidget(self.table, stretch=1)

        table_buttons = QHBoxLayout()
        table_buttons.addStretch(1)
        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(48)
        delete_button.setToolTip("حذفِ چکِ انتخاب‌شده")
        delete_button.clicked.connect(self._delete_selected_row)
        table_buttons.addWidget(delete_button)
        outer.addLayout(table_buttons)

        self.total_label = QLabel("")
        outer.addWidget(self.total_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("تایید")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        # همان باگِ autoDefault (نگاه کن به _MethodDetailsDialog): بدونِ این دو
        # خط + بدونِ override زیرِ keyPressEvent، با هر Enterِ زده‌شده در
        # زنجیره‌یِ فیلدها، دکمه‌یِ «تایید» هم به‌طورِ خودکار کلیک می‌شود و
        # _on_accept را زودتر از موعد صدا می‌زند — همان لحظه‌ای که هنوز چکی
        # به فهرست اضافه نشده، پس هشدارِ «حداقل یک چک» نمایش داده می‌شود.
        buttons.button(QDialogButtonBox.Ok).setAutoDefault(False)
        buttons.button(QDialogButtonBox.Cancel).setAutoDefault(False)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        for entry in self._checks:
            self._append_table_row(entry)
        self._update_total()

    def keyPressEvent(self, event) -> None:
        # طبقِ بررسیِ عملی: setAutoDefault(False) به‌تنهایی کافی نیست —
        # QDialogButtonBox با هر show() دوباره دکمه‌یِ «تایید» را default
        # می‌کند و QDialog.keyPressEvent با دیدنِ Enter (حتی اگر خودِ فیلد
        # returnPressed را برایِ جابه‌جاییِ فوکوس/افزودنِ چک مصرف کرده باشد)
        # آن را دوباره کلیک می‌کند. چون همه‌یِ فیلدها زنجیره‌یِ Enterِ خودشان
        # را دارند، دیگر نیازی به این رفتارِ پیش‌فرضِ QDialog نیست.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def _current_entry(self) -> dict | None:
        amount = decimal.Decimal(str(self.amount_field.value()))
        if amount <= 0:
            return None
        bank_label = self.bank_combo.currentText() if self.bank_combo.currentData() is not None else None
        entry = {
            "check_serial": self.serial_field.text().strip() or None,
            "check_no": self.no_field.text().strip(),
            "iban": self.iban_field.text().strip() or None,
            "check_bank_name": bank_label,
            "amount": amount,
            "due_date": self.due_field.date(),
        }
        if self._direction == "RECEIPT":
            entry.update(
                bank_id=self.bank_combo.currentData(),
                bank_account_no=self.account_no_field.text().strip() or None,
                party_name=self.owner_field.text().strip() or None,
                national_id=self.national_id_field.text().strip() or None,
                phone=self.phone_field.text().strip() or None,
            )
        else:
            entry.update(
                payee_bank_id=self.bank_combo.currentData(),
                payee_account_no=self.account_no_field.text().strip() or None,
                payee_name=self.owner_field.text().strip() or None,
                payee_national_id=self.national_id_field.text().strip() or None,
                payee_phone=self.phone_field.text().strip() or None,
                sayad_no=self.sayad_field.text().strip() or None,
            )
        return entry

    def _append_table_row(self, entry: dict) -> None:
        row_index = self.table.rowCount()
        self.table.insertRow(row_index)
        self.table.setItem(row_index, 0, QTableWidgetItem(entry.get("check_no") or ""))
        second_col = entry.get("sayad_no") if self._direction == "PAYMENT" else entry.get("check_bank_name")
        self.table.setItem(row_index, 1, QTableWidgetItem(second_col or ""))
        self.table.setItem(row_index, 2, QTableWidgetItem(numerals.format_money(entry["amount"], self._decimal_places)))
        self.table.setItem(
            row_index, 3, QTableWidgetItem(entry.get("party_name") or entry.get("payee_name") or "")
        )

    def _refresh_table(self) -> None:
        self.table.setRowCount(0)
        for entry in self._checks:
            self._append_table_row(entry)

    def _clear_fields(self, *, after_edit: bool = False) -> None:
        if self._direction == "PAYMENT" and not after_edit:
            # طبقِ درخواستِ صریحِ آیتمِ ۴: بعدِ افزودنِ یک چکِ پرداختی،
            # اطلاعاتِ مشترک (سریال/سررسید) دست‌نخورده می‌مانند — فقط
            # مبلغ صفر می‌شود، شماره‌یِ چک یک رقم افزایش می‌یابد، و
            # شماره‌یِ صیادی (که برایِ هر چک یکتاست) پاک می‌شود.
            self.amount_field.setValue(0)
            self._increment_check_no()
            self.sayad_field.clear()
            return
        self.serial_field.clear()
        self.no_field.clear()
        self.amount_field.setValue(0)
        self.due_field.setDate(datetime.date.today())
        self.sayad_field.clear()
        if self._direction == "RECEIPT":
            self.iban_field.clear()
            self.bank_combo.setCurrentIndex(0)
            self.account_no_field.clear()
            self.owner_field.clear()
            self.national_id_field.clear()
            self.phone_field.clear()

    def _increment_check_no(self) -> None:
        """طبقِ آیتمِ ۴: شماره‌یِ چکِ بعدی یک رقم بیشتر از قبلی — فقط اگر
        شماره‌یِ فعلی عددیِ خالص باشد (وگرنه دست‌نخورده می‌ماند، چون معلوم
        نیست کاربر چه الگویی در نظر داشته)."""
        current = numerals.to_ascii_digits(self.no_field.text().strip())
        if not current.isdigit():
            return
        self.no_field.setText(str(int(current) + 1).zfill(len(current)))

    def _edit_row(self, row: int, _column: int) -> None:
        """طبقِ درخواستِ صریح: دابل‌کلیک رویِ یک چکِ واردشده آن را برایِ
        ویرایش به فیلدهایِ بالا برمی‌گرداند — به‌جایِ حذفِ فوری."""
        entry = self._checks[row]
        self.serial_field.setText(entry.get("check_serial") or "")
        self.no_field.setText(entry.get("check_no") or "")
        self.iban_field.setText(entry.get("iban") or "")
        bank_id = entry.get("bank_id") if self._direction == "RECEIPT" else entry.get("payee_bank_id")
        bank_index = self.bank_combo.findData(bank_id)
        self.bank_combo.setCurrentIndex(bank_index if bank_index >= 0 else 0)
        account_no = entry.get("bank_account_no") if self._direction == "RECEIPT" else entry.get("payee_account_no")
        self.account_no_field.setText(account_no or "")
        self.amount_field.setValue(float(entry["amount"]))
        self.due_field.setDate(entry["due_date"])
        owner = entry.get("party_name") if self._direction == "RECEIPT" else entry.get("payee_name")
        self.owner_field.setText(owner or "")
        national_id = entry.get("national_id") if self._direction == "RECEIPT" else entry.get("payee_national_id")
        self.national_id_field.setText(national_id or "")
        phone = entry.get("phone") if self._direction == "RECEIPT" else entry.get("payee_phone")
        self.phone_field.setText(phone or "")
        self.sayad_field.setText(entry.get("sayad_no") or "")
        self._editing_index = row
        self.add_button.setToolTip("به‌روزرسانیِ این چک")
        self.serial_field.setFocus()

    def _delete_selected_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.removeRow(row)
        self._checks.pop(row)
        if self._editing_index == row:
            self._editing_index = None
            self.add_button.setToolTip("افزودنِ این چک به فهرست")
            self._clear_fields(after_edit=True)
        elif self._editing_index is not None and self._editing_index > row:
            self._editing_index -= 1
        self._update_total()

    def _commit_current_entry(self) -> bool:
        entry = self._current_entry()
        if entry is None:
            return False
        was_editing = self._editing_index is not None
        if self._editing_index is not None:
            self._checks[self._editing_index] = entry
            self._refresh_table()
            self._editing_index = None
            self.add_button.setToolTip("افزودنِ این چک به فهرست")
        else:
            self._checks.append(entry)
            self._append_table_row(entry)
        self._clear_fields(after_edit=was_editing)
        self._update_total()
        return True

    def _add_current(self) -> None:
        if self._commit_current_entry():
            self.serial_field.setFocus()

    def _update_total(self) -> None:
        total = sum((c["amount"] for c in self._checks), decimal.Decimal(0))
        text = (
            f"جمعِ مبلغِ چک‌ها: {numerals.format_money(total, self._decimal_places)} "
            f"({numerals.to_persian_digits(str(len(self._checks)))} چک)"
        )
        # طبقِ آیتمِ ۶: «راسِ» همینِ چک‌هایِ واردشده — تاریخِ میانگینِ وزنی.
        if self._checks:
            ras_date, _total = treasury_service.compute_check_ras(
                [(c["amount"], c["due_date"]) for c in self._checks]
            )
            text += f"    —    راس: {numerals.format_jalali_date(ras_date)}"
        self.total_label.setText(text)

    def _on_accept(self) -> None:
        # اگر چکی در فیلدها آماده ولی هنوز به فهرست افزوده/به‌روز نشده،
        # پیش از تایید خودکار اعمال می‌شود — تا کاربر مجبور نباشد حتماً
        # «+ افزودن»/«به‌روزرسانی» را جداگانه بزند.
        self._commit_current_entry()
        if not self._checks:
            QMessageBox.warning(self, "چکِ دریافتی", "حداقل یک چک وارد کنید.")
            return
        self.accept()

    def result_checks(self) -> list[dict]:
        return list(self._checks)

    def result_checkbook_id(self) -> int | None:
        return self.checkbook_combo.currentData() if self.checkbook_combo is not None else None

    def result_bank_account_detail_id(self) -> int | None:
        return self.issuing_bank_combo.currentData() if self.issuing_bank_combo is not None else None

    def result_fund_detail_account_id(self) -> int | None:
        return self.fund_combo.currentData() if self.fund_combo is not None else None

    def result_person_detail_account_id(self) -> int | None:
        if self.preset_person_detail_id is not None:
            return self.preset_person_detail_id
        if self.person_detail_combo is not None:
            return self.person_detail_combo.currentData()
        return None

    def result_person_detail_label(self) -> str:
        # طبقِ گزارشِ صریح: این برچسب فقط در متنِ شرحِ خودکارِ سند مصرف
        # می‌شود — پس فقط نام، بدونِ کد (combo خودش برایِ جست‌وجو هنوز
        # کد+نام نشان می‌دهد).
        if self.preset_person_detail_id is not None:
            return self.preset_person_detail_label
        if self.person_detail_combo is not None:
            selected_id = self.person_detail_combo.currentData()
            return self._person_detail_names.get(selected_id, self.person_detail_combo.currentText())
        return ""


class _RowAmountField(_AmountField):
    """طبقِ آیتمِ ۶: فشردنِ Space در این فیلد، باقیمانده‌یِ محاسبه‌شده توسطِ
    `remaining_getter` را در خودش کپی می‌کند — هم در فرمِ دریافت هم پرداخت."""

    def __init__(self, remaining_getter=None) -> None:
        super().__init__()
        self._remaining_getter = remaining_getter

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and self._remaining_getter is not None:
            remaining = self._remaining_getter()
            if remaining is not None:
                self.setValue(float(remaining))
                event.accept()
                return
        super().keyPressEvent(event)


class _HeaderAmountField(_AmountField):
    """طبقِ گزارشِ صریح: اگر مبلغِ بالای فرمِ دریافت/پرداخت هنوز خالی/صفر
    است، فشردنِ Space جمعِ مبلغِ ردیف‌هایِ واردشده را در آن قرار می‌دهد —
    عکسِ آیتمِ ۶ (که باقیماندهِ هدر را در ردیف کپی می‌کند). اگر خودِ فیلد از
    قبل مقداری داشته باشد، Space کارِ معمولِ خودش (تایپِ فاصله) را
    می‌کند — این فیلد فقط برایِ حالتِ خالی‌بودن است."""

    def __init__(self, rows_total_getter=None) -> None:
        super().__init__()
        self._rows_total_getter = rows_total_getter

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and self._rows_total_getter is not None and self.value() == 0:
            rows_total = self._rows_total_getter()
            if rows_total:
                self.setValue(float(rows_total))
                event.accept()
                return
        super().keyPressEvent(event)


class _MethodRow:
    def __init__(self, screen: "TreasuryVoucherScreen") -> None:
        self._screen = screen
        self.details: dict = {}
        # طبقِ درخواستِ صریح: اگر این ردیف (با هر روشی -- معمولاً نقد/
        # بانک/چک) درواقع وصولِ یکی از اقساطِ ازپیش‌برنامه‌ریزی‌شده باشد.
        self.collect_installment_line_id: int | None = None

        self.method_combo = _EnterComboBox()
        method_codes = list(_RECEIPT_METHOD_CODES if screen.direction == "RECEIPT" else _PAYMENT_METHOD_CODES)
        # طبقِ آیتمِ ۷: روش‌هایِ سفارشیِ همین شرکت/جهت (اگر تعریف شده باشند)
        # بعدِ روش‌هایِ ثابت اضافه می‌شوند.
        method_codes += screen._custom_method_codes
        for code in method_codes:
            self.method_combo.addItem(_METHOD_LABELS.get(code, code), code)
        self.method_combo.enterPressed.connect(self._on_method_return)
        self.method_combo.currentIndexChanged.connect(lambda _i: self._regenerate_description())
        self.method_combo.currentIndexChanged.connect(lambda _i: self._update_discount_percent_visibility())

        self.amount_field = _RowAmountField(screen._remaining_amount)
        self.amount_field.setDecimals(screen.currency_decimal_places)
        self.amount_field.returnPressed.connect(lambda: self.description_field.setFocus())
        self.amount_field.valueChanged.connect(lambda _v: self._regenerate_description())
        self.amount_field.valueChanged.connect(lambda _v: screen._update_rows_summary())

        # طبقِ آیتمِ ۱۰: در روشِ تخفیف، پیش از واردکردنِ خودِ مبلغ، می‌شود
        # درصدِ تخفیف را وارد کرد — مبلغِ ردیف خودکار از رویِ همین درصد و
        # جمعِ مبلغِ هدر (کلِ مبلغِ دریافتی/پرداختی) محاسبه می‌شود. فقط
        # برایِ روشِ تخفیف نمایش داده می‌شود (در _update_discount_percent_visibility).
        self.discount_percent_field = _AmountField()
        self.discount_percent_field.setDecimals(2)
        self.discount_percent_field.setMaximumWidth(56)
        self.discount_percent_field.setToolTip("درصدِ تخفیف — بر اساسِ جمعِ مبلغِ هدر، مبلغِ این ردیف را خودکار پر می‌کند.")
        self.discount_percent_field.setVisible(False)
        self.discount_percent_field.valueChanged.connect(self._on_discount_percent_changed)
        self.discount_percent_label = QLabel("٪")
        self.discount_percent_label.setVisible(False)

        self.amount_cell = QWidget()
        amount_cell_layout = QHBoxLayout(self.amount_cell)
        amount_cell_layout.setContentsMargins(0, 0, 0, 0)
        amount_cell_layout.setSpacing(2)
        amount_cell_layout.addWidget(self.discount_percent_field)
        amount_cell_layout.addWidget(self.discount_percent_label)
        amount_cell_layout.addWidget(self.amount_field, stretch=1)

        self.description_field = QLineEdit()
        self.description_field.returnPressed.connect(lambda: screen._focus_next_row_after(self))

        # طبقِ گزارشِ صریح («بعضی فرم‌ها روی دکمه‌هاش نوشته داره و نصف
        # نوشته‌هاست»): این دکمه در ستونی به عرضِ ۱۰۰px می‌نشست — متنِ
        # «جزئیات…» حتی با سه‌نقطه‌یِ دستی هم گاهی نصفه دیده می‌شد. آیکنِ
        # تنها هرگز بریده نمی‌شود.
        self.details_button = QPushButton("📋")
        self.details_button.setObjectName("iconButton")
        self.details_button.setFixedWidth(44)
        self.details_button.setToolTip("جزئیاتِ این ردیف")
        self.details_button.clicked.connect(self._open_details)

        # طبقِ درخواستِ صریح («روشِ دریافت/پرداختِ اقساطی»): وصولِ یک قسطِ
        # ازپیش‌برنامه‌ریزی‌شده -- مستقل از روشِ انتخاب‌شده (نقد/بانک/چک) --
        # از همین دکمه انتخاب می‌شود؛ اگر قسطی برایِ همین طرفِ‌حساب در
        # انتظار نباشد، دکمه غیرفعال می‌ماند.
        self.installment_link_button = QPushButton("🔗")
        self.installment_link_button.setObjectName("iconButton")
        self.installment_link_button.setFixedWidth(44)
        self.installment_link_button.setToolTip("اتصال به یک قسطِ درانتظار (این ردیف وصولِ کدام قسط است؟)")
        self.installment_link_button.clicked.connect(self._open_installment_link)

        self.remove_button = QPushButton("✕")
        # طبقِ گزارشِ صریح: با dangerButtonِ همیشه‌شفاف، دکمه‌یِ حذفِ ردیف
        # تا هاور نکردن اصلاً معلوم نبود — dangerIconButton همیشه یک
        # زمینه/لبه‌یِ قرمزِ کم‌رنگ دارد.
        self.remove_button.setObjectName("dangerIconButton")
        self.remove_button.setFixedWidth(44)
        self.remove_button.setToolTip("حذفِ این ردیف")
        self.remove_button.clicked.connect(lambda: screen._remove_row(self))

        self._update_discount_percent_visibility()

    def _update_discount_percent_visibility(self) -> None:
        """طبقِ آیتمِ ۱۰: فیلدِ درصدِ تخفیف فقط برایِ روشِ تخفیف نمایش
        داده می‌شود."""
        is_discount = self.method_combo.currentData() == "DISCOUNT"
        self.discount_percent_field.setVisible(is_discount)
        self.discount_percent_label.setVisible(is_discount)

    def _on_discount_percent_changed(self, value: float) -> None:
        """طبقِ آیتمِ ۱۰: با واردکردنِ درصد، مبلغِ ردیف خودکار از رویِ
        همان درصد ضربدرِ جمعِ مبلغِ هدر (کلِ مبلغِ دریافتی/پرداختی)
        محاسبه و در فیلدِ مبلغ گذاشته می‌شود — کاربر می‌تواند بعداً هم
        خودِ مبلغ را دستی اصلاح کند."""
        if value <= 0:
            return
        header_total = float(self._screen.total_amount_field.value())
        if header_total <= 0:
            return
        self.amount_field.setValue(header_total * value / 100)

    def _on_method_return(self) -> None:
        method = self.method_combo.currentData()
        if method in _METHODS_WITHOUT_DETAILS or self._screen.company_id is None:
            self._regenerate_description()
            self.amount_field.setFocus()
            return
        self._open_details()

    def _open_details(self) -> None:
        method = self.method_combo.currentData()
        if method in _METHODS_WITHOUT_DETAILS or self._screen.company_id is None:
            self._regenerate_description()
            self.amount_field.setFocus()
            return
        if method == "CHECK":
            # طبقِ درخواستِ صریح: «پرداخت چند چکه هم باشه» — دیالوگِ
            # چندچکیِ _CheckEntryDialog دیگر مخصوصِ دریافت نیست، هردو جهت
            # را با فیلدهایِ متناظرِ خودشان (دسته‌چک/حسابِ بانکیِ
            # صادرکننده برایِ پرداخت) پوشش می‌دهد.
            direction = self._screen.direction
            dialog = _CheckEntryDialog(
                self._screen.company_id,
                self.details.get("checks") or [],
                self._screen,
                mapping_key=f"{direction}_{method}",
                current_person_detail_id=self.details.get("person_detail_account_id"),
                header_person_group_id=self._screen._counterparty_person_group_id(),
                header_counterparty_detail_id=self._screen.account_combo.currentData(),
                direction=direction,
                current_checkbook_id=self.details.get("checkbook_id"),
                current_bank_account_detail_id=self.details.get("detail_account_id"),
                decimal_places=self._screen.currency_decimal_places,
                header_payee_info=self._screen._counterparty_payee_info() if direction == "PAYMENT" else None,
            )
            if dialog.exec() == QDialog.Accepted:
                checks = dialog.result_checks()
                self.details = {
                    "checks": checks,
                    "person_detail_account_id": dialog.result_person_detail_account_id(),
                    "person_detail_account_label": dialog.result_person_detail_label(),
                }
                if direction == "PAYMENT":
                    self.details["checkbook_id"] = dialog.result_checkbook_id()
                    self.details["detail_account_id"] = dialog.result_bank_account_detail_id()
                else:
                    self.details["detail_account_id"] = dialog.result_fund_detail_account_id()
                total = sum((c["amount"] for c in checks), decimal.Decimal(0))
                self.amount_field.setValue(float(total))
                self._regenerate_description()
                self.description_field.setFocus()
            return
        if _is_mapping_only_method(method):
            # طبقِ درخواستِ صریح: اگر تفصیلیِ این روش از پیش در تنظیمات
            # تخصیص یافته، دیگر دیالوگ باز نمی‌شود (خودکار اعمال می‌شود)؛
            # اگر نه پیش‌تخصیص هست نه هیچ گزینه‌ای، دیالوگِ خالی هم باز نمی‌شود.
            mapping_key = f"{self._screen.direction}_{method}"
            _account_id, preset, required_label, options, _account_id_by_detail = _resolve_row_detail_sources(
                self._screen.company_id,
                mapping_key,
                self._screen._covered_dimension_type_ids(),
                self._screen._counterparty_person_group_id(),
            )
            if preset is not None:
                self.details = {"detail_account_id": preset[0], "detail_account_label": preset[1]}
                self._regenerate_description()
                self.amount_field.setFocus()
                return
            # طبقِ باگ‌فیکس: «بن» برخلافِ نقد/بانک/تخفیف/کالابرگ/تهاتر، فیلدهایِ
            # اختصاصیِ خودش (سریال/مشخصات) را دارد که همیشه لازم‌اند — حتی
            # وقتی تفصیلی چیزی برایِ پرسیدن ندارد (مثلاً چون طرفِ‌حسابِ هدر
            # همان محدودیت را ارضا کرده). قبلاً در این حالت کلِ دیالوگ حتی
            # بازهم نمی‌شد و سریال/مشخصاتِ بن هم فراموش می‌شد.
            if not options and method != "VOUCHER":
                # طبقِ گزارشِ صریح: وقتی معینِ نگاشته‌شده واقعاً به یک بُعدِ
                # تفصیلی نیاز دارد (required_label پر است) ولی هیچ تفصیلیِ
                # فعالی زیرِ آن بُعد تعریف نشده، قبلاً این حالت کاملاً بی‌صدا
                # نادیده گرفته می‌شد — کاربر فکر می‌کرد برنامه باگ دارد،
                # درحالی‌که فقط تفصیلیِ لازم هنوز ساخته نشده بود. حالا این
                # وضعیت با یک پیامِ روشن مشخص می‌شود.
                if required_label:
                    theme.set_status_label(
                        self._screen.status_label,
                        f"معینِ نگاشته‌شده برایِ «{_METHOD_LABELS.get(method, method)}» به «{required_label}» "
                        "نیاز دارد، ولی هیچ تفصیلیِ فعالی در آن گروه تعریف نشده — "
                        "ابتدا از صفحه‌یِ «تفصیلی‌ها» یک حساب در آن گروه بسازید.",
                        ok=False,
                    )
                self._regenerate_description()
                self.amount_field.setFocus()
                return
        dialog = _MethodDetailsDialog(
            self._screen.direction,
            method,
            self._screen.company_id,
            self.details,
            self._screen,
            covered_dimension_type_ids=self._screen._covered_dimension_type_ids(),
            header_person_group_id=self._screen._counterparty_person_group_id(),
            decimal_places=self._screen.currency_decimal_places,
            counterparty_detail_account_id=self._screen.account_combo.currentData(),
        )
        if dialog.exec() == QDialog.Accepted:
            self.details = dialog.result_data()
            if method == "CHECK_DISBURSEMENT" and "check_amount" in self.details:
                self.amount_field.setValue(float(self.details["check_amount"]))
                self._regenerate_description()
                self.description_field.setFocus()
            else:
                self._regenerate_description()
                self.amount_field.setFocus()

    def _open_installment_link(self) -> None:
        """طبقِ درخواستِ صریح («روشِ دریافت/پرداختِ اقساطی»): این ردیف را
        به یکی از اقساطِ درانتظارِ همان طرفِ‌حسابِ سند وصل می‌کند -- با
        تاییدِ سند، آن قسط PAID می‌شود و خودکار به‌عنوانِ یک تسویه رویِ
        فاکتورِ اصلیِ همان طرح هم ثبت می‌شود."""
        company_id = self._screen.company_id
        counterparty_id = self._screen.account_combo.currentData()
        if company_id is None or counterparty_id is None:
            theme.set_status_label(self._screen.status_label, "ابتدا طرفِ‌حساب را انتخاب کنید.", ok=False)
            return
        pending = installments_service.list_installments(
            company_id, status_codes=["PENDING", "OVERDUE"], counterparty_detail_account_id=counterparty_id,
        )
        if not pending:
            theme.set_status_label(self._screen.status_label, "قسطِ درانتظاری برایِ این طرفِ‌حساب یافت نشد.", ok=False)
            return
        dialog = QDialog(self._screen)
        dialog.setWindowTitle("اتصال به قسط")
        form = QFormLayout(dialog)
        combo = _make_searchable_combo(
            [(None, "(بدونِ اتصال)")]
            + [
                (
                    line.line_id,
                    f"فاکتور #{numerals.to_persian_digits(str(line.document_id))} — قسطِ #{numerals.to_persian_digits(str(line.installment_no))} — "
                    f"{numerals.format_money(line.amount, self._screen.currency_decimal_places)} — سررسید {numerals.format_jalali_date(line.due_date)}",
                )
                for line in pending
            ]
        )
        if self.collect_installment_line_id is not None:
            index = combo.findData(self.collect_installment_line_id)
            if index >= 0:
                combo.setCurrentIndex(index)
        form.addRow("قسط", combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("تایید")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.collect_installment_line_id = combo.currentData()
            if self.collect_installment_line_id is not None:
                selected = next(line for line in pending if line.line_id == self.collect_installment_line_id)
                if self.amount_field.value() == 0:
                    self.amount_field.setValue(float(selected.amount))
                self.installment_link_button.setStyleSheet("font-weight: bold;")
            else:
                self.installment_link_button.setStyleSheet("")

    def _regenerate_description(self) -> None:
        """طبقِ درخواستِ صریح: شرحِ هر ردیف خودکار از رویِ قالبِ همان روش
        (قابلِ‌ویرایش در تنظیمات) ساخته و نمایش داده می‌شود — کاربر بعداً
        هم می‌تواند دستی ویرایشش کند."""
        if self._screen.company_id is None:
            return
        method = self.method_combo.currentData()
        if method is None:
            return
        template_text = self._screen._description_templates.get(f"{self._screen.direction}_{method}", "")
        if not template_text:
            return
        try:
            amount = decimal.Decimal(str(self.amount_field.value()))
        except (ValueError, decimal.InvalidOperation):
            amount = decimal.Decimal(0)
        if amount <= 0:
            return  # هنوز چیزِ معناداری برایِ توصیف نیست — شرحِ ردیفِ خالی را با متنِ نصفه‌نیمه پر نکن
        context = {
            "تفصیلی": self.details.get("detail_account_label") or "",
            "مبلغ": numerals.format_money(amount, self._screen.currency_decimal_places) if amount else "",
            "طرف_حساب": self._screen._counterparty_label(),
            "تعداد": "",
            "یادداشت": "",
        }
        if method == "CHECK":
            checks = self.details.get("checks")
            if checks:
                context["تعداد"] = numerals.to_persian_digits(str(len(checks)))
            elif self.details.get("check_no"):
                context["تعداد"] = numerals.to_persian_digits("1")
        if method == "CHECK_DISBURSEMENT":
            received_check_ids = self.details.get("received_check_ids")
            if received_check_ids:
                context["تعداد"] = numerals.to_persian_digits(str(len(received_check_ids)))
            elif self.details.get("received_check_id"):
                context["تعداد"] = numerals.to_persian_digits("1")
        if method == "VOUCHER":
            context["یادداشت"] = " — ".join(
                bit for bit in (self.details.get("voucher_serial"), self.details.get("voucher_detail")) if bit
            )
        rendered = treasury_service.render_description_template(template_text, context)
        if rendered:
            self.description_field.setText(rendered)

    def to_method_line(self) -> treasury_service.MethodLine | None:
        method = self.method_combo.currentData()
        try:
            amount = decimal.Decimal(str(self.amount_field.value()))
        except (ValueError, decimal.InvalidOperation):
            amount = decimal.Decimal(0)
        if amount <= 0:
            return None
        kwargs = {
            "method": method,
            "amount": amount,
            "description": self.description_field.text().strip(),
        }
        if _is_mapping_only_method(method):
            kwargs["detail_account_id"] = self.details.get("detail_account_id")
            kwargs["account_id_override"] = self.details.get("account_id_override")
        elif method == "CHECK":
            kwargs["person_detail_account_id"] = self.details.get("person_detail_account_id")
            if "checks" in self.details:
                # طبقِ درخواستِ صریح: چک (هم دریافت هم پرداخت) همیشه از
                # دیالوگِ چندچکیِ _CheckEntryDialog می‌آید — checkbook_id/
                # detail_account_id فقط برایِ پرداخت پر می‌شوند (دسته‌چک و
                # حسابِ بانکیِ صادرکننده‌یِ مشترکِ کلِ ردیف).
                kwargs["checks"] = self.details["checks"]
                kwargs["checkbook_id"] = self.details.get("checkbook_id")
                kwargs["detail_account_id"] = self.details.get("detail_account_id")
            else:
                # فقط برایِ حالتِ نادر که کاربر بدونِ بازکردنِ دیالوگ
                # («جزئیات…») مستقیماً مبلغ را پر و ثبت کند — این‌جا
                # self.details هنوز خالی است.
                kwargs.update(
                    detail_account_id=self.details.get("detail_account_id"),
                    check_no=self.details.get("check_no") or "",
                    check_bank_name=self.details.get("check_bank_name"),
                    check_due_date=self.details.get("check_due_date"),
                    check_party_name=self.details.get("check_party_name"),
                    checkbook_id=self.details.get("checkbook_id"),
                )
        elif method == "CHECK_DISBURSEMENT":
            kwargs["received_check_ids"] = self.details.get("received_check_ids")
            kwargs["received_check_id"] = self.details.get("received_check_id")
            kwargs["person_detail_account_id"] = self.details.get("person_detail_account_id")
        elif method == "INSTALLMENT":
            kwargs["installment_document_id"] = self.details.get("installment_document_id")
            kwargs["installment_count"] = self.details.get("installment_count")
            kwargs["installment_first_due_date"] = self.details.get("installment_first_due_date")
        # طبقِ درخواستِ صریح: هر ردیفی (نه فقط اقساط) می‌تواند وصولِ یک
        # قسطِ ازپیش‌برنامه‌ریزی‌شده باشد -- با دکمه‌یِ «🔗» انتخاب می‌شود.
        kwargs["collect_installment_line_id"] = self.collect_installment_line_id
        return treasury_service.MethodLine(**kwargs)


class _LinkInvoicesDialog(LayoutEditMixin, QDialog):
    """طبقِ درخواستِ صریح («در فرمِ دریافت/پرداخت هم دکمه‌ای باشد که به
    فاکتورهایِ تسویه‌نشده لینک باشد و بتوان مبلغِ تسویه را برایِ
    فاکتورهایِ همان شخص وارد کرد»): مسیرِ معکوسِ همان چیزی که در
    commercial_settlement.py ساخته شد — این‌جا خودِ فرمِ دریافت/پرداخت
    فهرستِ فاکتورهایِ بازِ طرفِ‌حسابِ انتخاب‌شده را نشان می‌دهد."""

    def __init__(self, parent: QWidget, statuses: list, docs_by_id: dict, direction: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("لینک به فاکتورهایِ بازِ این طرفِ‌حساب")
        self.setMinimumWidth(560)
        self._statuses = statuses
        self._qty_fields: dict[int, _AmountField] = {}
        invoice_title = "فاکتورِ فروش" if direction == "RECEIPT" else "فاکتورِ خرید"

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("مبلغِ تسویه‌یِ هرکدام از فاکتورهایِ بازِ این طرفِ‌حساب را مشخص کنید (پیش‌فرض: صفر)."))

        table = QTableWidget(len(statuses), len(_LINK_INVOICE_COLUMNS))
        table.setHorizontalHeaderLabels(_LINK_INVOICE_COLUMNS)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for row_index, status in enumerate(statuses):
            doc = docs_by_id[status.document_id]
            values = [
                invoice_title,
                numerals.to_persian_digits(str(doc.document_no)),
                numerals.format_jalali_date(status.due_date) if status.due_date else "—",
                numerals.format_company_amount(status.total_amount),
                numerals.format_company_amount(status.remaining_amount),
            ]
            for col_index, value in enumerate(values):
                table.setItem(row_index, col_index, QTableWidgetItem(value))
            qty_field = _AmountField()
            qty_field.setValue(0)
            self._qty_fields[status.document_id] = qty_field
            table.setCellWidget(row_index, len(_LINK_INVOICE_COLUMNS) - 1, qty_field)
        table.resizeRowsToContents()
        layout.addWidget(table)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("تایید")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        # هم‌الگو با _ConvertToInvoiceDialog در commercial_document.py --
        # جلوگیری از باگِ autoDefaultِ QDialogButtonBox.
        buttons.button(QDialogButtonBox.Ok).setAutoDefault(False)
        buttons.button(QDialogButtonBox.Cancel).setAutoDefault(False)
        layout.addWidget(buttons)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_accept(self) -> None:
        entries = {doc_id: decimal.Decimal(str(field.value())) for doc_id, field in self._qty_fields.items() if field.value() > 0}
        if not entries:
            self.status_label.setText("حداقل برایِ یک فاکتور مبلغی وارد کنید.")
            return
        for status in self._statuses:
            amount = entries.get(status.document_id)
            if amount is not None and amount > status.remaining_amount:
                self.status_label.setText("مبلغِ واردشده برایِ یک فاکتور از مانده‌اش بیشتر است.")
                return
        self.accept()

    def result_entries(self) -> dict[int, decimal.Decimal]:
        return {doc_id: decimal.Decimal(str(field.value())) for doc_id, field in self._qty_fields.items() if field.value() > 0}


class TreasuryVoucherScreen(FieldHelpMixin, FormScreenBase):
    def __init__(self, direction: str, main_window=None) -> None:
        super().__init__()
        self.direction = direction  # "RECEIPT" یا "PAYMENT"
        # طبقِ آیتمِ ۹: برایِ بازکردنِ گزارشِ معینِ طرفِ‌حساب از همین فرم لازم
        # است — هم‌الگو با JournalEntriesListScreen (شکلِ شناخته‌شده‌یِ
        # ناوبریِ صفحه‌به‌صفحه در این برنامه).
        self._main_window = main_window
        self.company_id: int | None = None
        self.currency_decimal_places = 0
        # طبقِ درخواستِ صریح: «در بالای فرم دریافت، دریافتِ ارزی هم داشته
        # باشیم و نرخ را از تنظیمات/آخرین نرخِ ارز بخواند» — هم‌الگو با
        # کمبویِ ارزِ سندِ حسابداری در journal_entry.py.
        self._base_currency_id: int | None = None
        self._currency_by_id: dict[int, object] = {}
        self.header_currency_id: int | None = None
        self.header_exchange_rate: decimal.Decimal | None = None
        self.account_options: list[tuple[int, str]] = []
        self._detail_combos: dict[int, QComboBox] = {}
        self._method_rows: list[_MethodRow] = []
        self._custom_method_codes: list[str] = []
        # طبقِ درخواستِ صریح: در فرمِ دریافت/پرداخت، طرفِ حساب یک تفصیلی است
        # (نه معین) — فقط تفصیلی‌هایِ گروه‌هایی که در «انواعِ سندِ دریافت/
        # پرداخت» (تنظیماتِ سیستم/خزانه‌داری) نگاشته شده‌اند پیشنهاد
        # می‌شوند؛ معین و بقیه‌یِ تفصیلی‌هایِ لازم از رویِ همان نگاشت خودکار
        # حل می‌شوند.
        # کلید: detail_account_id -> (account_id، dimension_type_idِ حل‌شده)
        self._counterparty_index: dict[int, tuple[int, int]] = {}
        # قالبِ متنِ خودکارِ شرحِ هر روش — در refresh() از تنظیمات بارگذاری
        # می‌شود (به‌جایِ کوئریِ جداگانه به‌ازایِ هر کلیدزنیِ مبلغ).
        self._description_templates: dict[str, str] = {}
        # طبقِ درخواستِ صریح («از همان فرمِ تسویه‌یِ فاکتورها، دکمه‌یِ تسویه
        # فرمِ دریافت/پرداخت را باز کند و رفرنس بدهد» + «مبلغِ دریافتی برایِ
        # چند فاکتورِ هم‌زمان وارد شود»): وقتی این فرم از طریقِ
        # commercial_settlement.py برایِ تسویه‌یِ یک یا چند فاکتورِ مشخص
        # باز می‌شود، فهرستِ (شناسه‌یِ فاکتور، مبلغِ همان فاکتور) این‌جا
        # نگه داشته می‌شود تا بعدِ ثبتِ موفقِ سند، خودکار به‌عنوانِ تسویه‌یِ
        # همه‌یِ آن فاکتورها (هرکدام با مبلغِ خودش) هم ثبت شود.
        self._settle_invoices: list[tuple[int, decimal.Decimal]] = []

        noun = "دریافت" if direction == "RECEIPT" else "پرداخت"
        row_methods_hint = (
            "نقد/بانک/چک/تخفیف/کالابرگ/بن/تهاتر" if direction == "RECEIPT" else "نقد/بانک/چک/تخفیف/خرجِ چک/تهاتر"
        )

        # هم‌الگو با هدرِ فرمِ سندِ حسابداری (journal_entry.py): کارتِ هدر با
        # QGridLayout و عرض/کِشِ ستونِ مشخص — نه QFormLayout با عرضِ کاملِ
        # پیش‌فرض. طبقِ گزارشِ صریح («فیلدهایِ هدر جمع‌وجورتر باشند تا جایِ
        # بیشتری برایِ ردیف‌ها بماند»): حاشیه/فاصله‌یِ کارتِ هدر فشرده‌تر شد
        # و طرفِ‌حساب+تاریخ در یک ردیف، شرح+جمعِ مبلغ در ردیفِ بعدی جا
        # گرفتند (به‌جایِ یک فیلد در هر ردیف).
        # طبقِ آیتمِ ۱ (اسکرول+فوترِ ثابت): این فرم پیش‌تر اصلاً اسکرول
        # نداشت — روی FormScreenBase (widgets.py) بازسازی شده تا وقتی
        # محتوا از ارتفاعِ زیرپنجره بیشتر شود، دکمه‌یِ ثبت هیچ‌وقت از دید
        # خارج نشود. بدنه در self.body_layout، دکمه/وضعیت در self.footer_layout.
        layout = self.body_layout
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(5)

        # طبقِ نمونه‌طراحیِ استپردار/کارت‌رنگیِ ارسالیِ کاربر: نوارِ گام‌نمایِ
        # بصری (اطلاعاتِ سند -> ردیف‌ها؛ صرفاً اسکرول می‌کند، صفحه‌بندیِ
        # واقعی نیست، پس زنجیره‌یِ کیبورد/اعتبارسنجیِ پایین دست‌نخورده
        # می‌ماند) + نوارِ کارت‌هایِ رنگیِ خلاصه (جمعِ هدر/جمعِ ردیف‌ها/اختلاف)
        # بالایِ فرم.
        self.step_stepper = SectionStepper(["اطلاعاتِ سند", "ردیف‌ها"])
        layout.addWidget(self.step_stepper)

        self.summary_cards = SummaryCardBar({
            "total": SummaryCard(f"جمعِ مبلغِ {noun}", role="info"),
            "rows_total": SummaryCard("جمعِ ردیف‌ها", role="neutral"),
            "diff": SummaryCard("اختلاف", role="success"),
        })
        layout.addWidget(self.summary_cards)

        header_card = QWidget()
        header_card.setObjectName("card")
        header_layout = QGridLayout(header_card)
        header_layout.setContentsMargins(10, 6, 10, 4)
        header_layout.setSpacing(3)

        self.title_label = QLabel(f"سندِ {noun}")
        self.title_label.setObjectName("pageTitle")
        header_layout.addWidget(self.title_label, 0, 0, 1, 5)

        header_layout.addWidget(QLabel("طرفِ حساب (تفصیلی)"), 1, 0)
        # طبقِ آیتم‌هایِ ۹/۱۱: کنارِ خودِ کمبویِ طرفِ‌حساب، دو دکمه‌یِ میان‌بر —
        # افزودنِ سریعِ طرفِ‌حسابِ تازه (بدونِ خروج از فرم) و بازکردنِ
        # گزارشِ معینِ همین طرفِ‌حساب.
        account_row = QHBoxLayout()
        account_row.setContentsMargins(0, 0, 0, 0)
        account_row.setSpacing(3)
        self.account_combo = _make_searchable_combo([])
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        account_row.addWidget(self.account_combo, stretch=1)
        self.quick_add_button = QPushButton("+")
        # طبقِ گزارشِ صریح: این دکمه‌یِ آیکونی با flatButtonِ همیشه‌شفاف
        # به‌سختی دیده می‌شد — iconButton همیشه یک زمینه/لبه‌یِ ملایم دارد.
        self.quick_add_button.setObjectName("iconButton")
        self.quick_add_button.setToolTip("بازکردنِ فرمِ تعریفِ تفصیلی (برایِ ساختنِ طرفِ‌حسابِ تازه)")
        self.quick_add_button.setMaximumWidth(28)
        self.quick_add_button.clicked.connect(self._quick_add_counterparty)
        account_row.addWidget(self.quick_add_button)
        self.ledger_button = QPushButton("📒")
        self.ledger_button.setObjectName("iconButton")
        self.ledger_button.setToolTip("گزارشِ معینِ طرفِ‌حساب")
        self.ledger_button.setMaximumWidth(28)
        self.ledger_button.clicked.connect(self._open_counterparty_ledger)
        account_row.addWidget(self.ledger_button)
        # طبقِ درخواستِ صریح («در فرمِ دریافت/پرداخت هم دکمه‌ای باشد که
        # به فاکتورهایِ تسویه‌نشده لینک باشد و بتوان مبلغِ تسویه را برایِ
        # فاکتورهایِ همان شخص وارد کرد»).
        self.link_invoices_button = QPushButton("🔗")
        self.link_invoices_button.setObjectName("iconButton")
        self.link_invoices_button.setToolTip("لینک به فاکتورهایِ بازِ این طرفِ‌حساب — واردکردنِ مبلغِ تسویه برایِ هرکدام")
        self.link_invoices_button.setMaximumWidth(28)
        self.link_invoices_button.clicked.connect(self._open_link_invoices_dialog)
        account_row.addWidget(self.link_invoices_button)
        header_layout.addLayout(account_row, 1, 1)

        # طبقِ درخواستِ صریح: مرکزِ هزینه/پروژه (اگر رویِ حسابِ طرف‌حساب
        # الزامی باشند) به‌جایِ یک ردیفِ جداگانه‌یِ زیرِ هدر، همین‌جا جلویِ
        # خودِ تفصیلیِ طرفِ‌حساب می‌آیند — افقی و جمع‌وجور.
        self.detail_container = QHBoxLayout()
        self.detail_container.setContentsMargins(0, 0, 0, 0)
        self.detail_container.setSpacing(4)
        header_layout.addLayout(self.detail_container, 1, 2)

        header_layout.addWidget(QLabel("تاریخ"), 1, 3)
        self.date_field = JalaliDateEdit("تاریخِ سند")
        header_layout.addWidget(self.date_field, 1, 4)

        # طبقِ آیتمِ ۸: ماندهٔ فعلی + ماهیتِ همین طرفِ‌حساب، بلافاصله زیرِ
        # ردیفِ طرفِ‌حساب/تاریخ.
        self.balance_label = QLabel("")
        self.balance_label.setObjectName("sectionHint")
        header_layout.addWidget(self.balance_label, 2, 0, 1, 5)

        header_layout.addWidget(QLabel("شرح"), 3, 0)
        self.description_field = QLineEdit()
        header_layout.addWidget(self.description_field, 3, 1, 1, 2)

        # طبقِ درخواستِ صریح: جمعِ مبلغِ هدر + جمعِ زنده‌یِ ردیف‌ها/اختلاف
        # (و رفتارِ Spaceِ متناظر) دیگر مخصوصِ دریافت نیست — پرداخت هم
        # عیناً همین رفتار را دارد.
        total_label_text = "جمعِ مبلغِ دریافتی" if direction == "RECEIPT" else "جمعِ مبلغِ پرداختی"
        header_layout.addWidget(QLabel(total_label_text), 3, 3)
        self.total_amount_field: _AmountField = _HeaderAmountField(self._rows_total)
        self.total_amount_field.setMaximumWidth(160)
        self.total_amount_field.valueChanged.connect(lambda _v: self._update_rows_summary())
        header_layout.addWidget(self.total_amount_field, 3, 4)

        # طبقِ درخواستِ صریح: جمعِ زنده‌یِ ردیف‌ها + اختلافش با جمعِ مبلغِ
        # هدر، همین‌جا نمایش داده شود.
        self.rows_summary_label: QLabel = QLabel("")
        # طبقِ گزارشِ صریح: این برچسب باید فونتِ درشت‌تری از بقیه‌یِ
        # sectionHintها داشته باشد — پس objectNameِ اختصاصیِ خودش را
        # دارد (rowsSummaryLabel در theme.py)، نه sectionHintِ عمومی.
        self.rows_summary_label.setObjectName("rowsSummaryLabel")
        header_layout.addWidget(self.rows_summary_label, 4, 0, 1, 5)

        # طبقِ آیتمِ ۶: راسِ زنده‌یِ همه‌یِ چک‌هایِ واردشده در ردیف‌هایِ
        # روشِ چک (هم دریافت هم پرداخت)، در بالایِ فرم.
        self.ras_label = QLabel("")
        self.ras_label.setObjectName("raasLabel")
        header_layout.addWidget(self.ras_label, 5, 0, 1, 5)

        # طبقِ درخواستِ صریح: «در بالای فرم دریافت، دریافتِ ارزی هم داشته
        # باشیم و نرخ را از تنظیمات/آخرین نرخِ ارز بخواند» — هم‌الگو با
        # کمبویِ ارزِ سند در journal_entry.py؛ اگر ارزِ پایه انتخاب شود
        # فیلدِ نرخ لازم نیست (نرخ همیشه ۱ است).
        header_layout.addWidget(QLabel(f"ارزِ سندِ {noun}"), 6, 0)
        self.currency_combo = QComboBox()
        self.currency_combo.currentIndexChanged.connect(self._on_currency_changed)
        header_layout.addWidget(self.currency_combo, 6, 1)
        self.rate_label = QLabel("نرخ به ارزِ پایه")
        header_layout.addWidget(self.rate_label, 6, 2)
        rate_row = QHBoxLayout()
        rate_row.setContentsMargins(0, 0, 0, 0)
        self.rate_field = QLineEdit()
        self.rate_field.editingFinished.connect(self._on_rate_changed)
        rate_row.addWidget(self.rate_field)
        self.rate_fetch_button = QPushButton("🌐")
        self.rate_fetch_button.setObjectName("iconButton")
        self.rate_fetch_button.setFixedWidth(44)
        self.rate_fetch_button.setToolTip("دریافتِ خودکارِ نرخِ ارز")
        self.rate_fetch_button.clicked.connect(self._on_fetch_rate)
        rate_row.addWidget(self.rate_fetch_button)
        header_layout.addLayout(rate_row, 6, 3, 1, 2)
        self.rate_label.setVisible(False)
        self.rate_field.setVisible(False)
        self.rate_fetch_button.setVisible(False)

        header_layout.setColumnStretch(0, 0)
        header_layout.setColumnStretch(1, 1)
        header_layout.setColumnStretch(2, 0)
        header_layout.setColumnStretch(3, 0)
        header_layout.setColumnStretch(4, 0)

        layout.addWidget(header_card)

        # --- زنجیره‌یِ Enterِ هدر: طرفِ‌حساب -> [مرکزِ هزینه/پروژه‌یِ پویا] ->
        # تاریخ -> شرح -> [جمعِ مبلغ] -> ردیفِ اول. چون کمبوهایِ پویا هر بار
        # در _on_account_changed از نو ساخته می‌شوند، نقطه‌یِ شروعِ زنجیره
        # (بعدِ طرفِ‌حساب) به‌جایِ اتصالِ ثابت، به‌صورتِ پویا در همان‌جا
        # تصمیم‌گیری می‌شود (_on_account_return).
        self.account_combo.lineEdit().returnPressed.connect(self._on_account_return)
        self.date_field.returnPressed.connect(lambda: self.description_field.setFocus())
        self.description_field.returnPressed.connect(lambda: self.total_amount_field.setFocus())
        self.total_amount_field.returnPressed.connect(self._focus_first_row_method)

        table_card = QWidget()
        table_card.setObjectName("card")
        table_card_layout = QVBoxLayout(table_card)
        table_card_layout.setContentsMargins(10, 8, 10, 10)
        table_card_layout.setSpacing(6)

        rows_header = QHBoxLayout()
        rows_title = QLabel(f"ردیف‌هایِ روش ({row_methods_hint})")
        rows_title.setObjectName("sectionHint")
        rows_header.addWidget(rows_title)
        rows_header.addStretch(1)
        add_row_button = QPushButton("➕")
        add_row_button.setObjectName("iconButton")
        add_row_button.setFixedWidth(36)
        add_row_button.setToolTip("افزودنِ ردیفِ روشِ تازه")
        add_row_button.clicked.connect(self._add_row)
        rows_header.addWidget(add_row_button)
        table_card_layout.addLayout(rows_header)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["روش", "مبلغ", "شرح", "جزئیات", "اقساط", ""])
        self.table.verticalHeader().setVisible(False)
        # طبقِ گزارشِ صریح («ارتفاعِ فیلدها کوچک/فشرده است»): Qt ارتفاعِ
        # ردیفِ جدول را با موردهایِ متنیِ ساده به‌درستی حساب می‌کند، ولی با
        # ویجت‌هایِ setCellWidget (کمبو/فیلدِ مبلغ با padding خودشان) نه —
        # دقیقاً هم‌الگو با جدولِ ردیف‌هایِ journal_entry.py.
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.setMinimumHeight(160)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 60)
        self.table.setColumnWidth(5, 36)
        table_card_layout.addWidget(self.table, stretch=1)

        layout.addWidget(table_card, stretch=1)

        self.step_stepper.register_sections(self._scroll, [header_card, table_card])

        # طبقِ گزارشِ صریح («برای همه‌ی دکمه‌ها آیکن به‌جایِ نوشته، با
        # تول‌تیپ برایِ توضیح»): حتی دکمه‌ی اصلیِ ثبت هم آیکنی شد — رنگِ
        # اکسنتِ primaryButton و عرضِ بزرگ‌تر همچنان آن را از بقیه‌ی
        # دکمه‌ها متمایز نگه می‌دارد.
        save_button = QPushButton("✔️")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(56)
        save_button.setToolTip(f"ثبتِ سندِ {noun}")
        save_button.clicked.connect(self._save)
        self.footer_layout.addWidget(save_button)
        self.footer_layout.addStretch(1)

        self.status_label = QLabel("")
        self.footer_layout.addWidget(self.status_label)

        help_fields: list[tuple[QWidget, str]] = [
            (
                self.account_combo,
                (
                    f"تفصیلیِ طرفِ حساب (مثلاً یک {'مشتریِ' if direction == 'RECEIPT' else 'تامین‌کننده‌یِ'} خاص) — "
                    f"فقط تفصیلی‌هایِ گروه‌هایی که در «انواعِ سندِ {noun}» (تنظیماتِ سیستم/تبِ خزانه‌داری) نگاشته شده‌اند "
                    "نشان داده می‌شوند؛ معین خودکار از رویِ همان نگاشت تعیین می‌شود. با Enter به فیلدِ بعدی می‌روید."
                ),
            ),
            (
                self.table,
                f"هر ردیف یک روشِ تسویه است ({row_methods_hint}) — می‌توانید یک {noun} را بینِ چند روش تقسیم کنید. "
                "با انتخابِ روش و Enter، فرمِ جزئیاتِ همان روش باز می‌شود؛ بعدِ تاییدِ جزئیات، به مبلغ/شرح و بعد ردیفِ بعدی می‌روید. "
                "شرحِ هر ردیف خودکار (از رویِ قالبِ قابلِ‌ویرایشِ همان روش در تنظیمات) پیشنهاد می‌شود — قابلِ‌ویرایشِ دستی هم هست.",
            ),
        ]
        help_fields.insert(
            1,
            (
                self.total_amount_field,
                f"جمعِ مبلغی که {noun} شده — جمعِ ردیف‌هایِ پایین باید دقیقاً با همین مبلغ برابر باشد تا سند ثبت شود.",
            ),
        )
        self.set_field_help(help_fields)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.company_id = self._company_id()
        if self.company_id is None:
            return
        self.account_options = self._build_counterparty_options()
        _fill_options(self.account_combo, self.account_options)

        self._base_currency_id = session.current_company.base_currency_id if session.current_company else None
        transactable = currencies_service.list_transactable_currencies(self.company_id)
        self._currency_by_id = {c.currency_id: c for c in transactable}
        base_currency = self._currency_by_id.get(self._base_currency_id)
        self.currency_decimal_places = base_currency.decimal_places if base_currency else 0
        self.total_amount_field.setDecimals(self.currency_decimal_places)

        self.currency_combo.blockSignals(True)
        self.currency_combo.clear()
        for c in transactable:
            label = c.iso_code + (" (پایه)" if c.currency_id == self._base_currency_id else "")
            self.currency_combo.addItem(label, c.currency_id)
        base_index = self.currency_combo.findData(self._base_currency_id)
        self.currency_combo.setCurrentIndex(max(base_index, 0))
        self.currency_combo.blockSignals(False)
        self.header_currency_id = None
        self.header_exchange_rate = None
        self.rate_label.setVisible(False)
        self.rate_field.setVisible(False)
        self.rate_fetch_button.setVisible(False)

        self._description_templates = {
            t.template_key: t.template_text for t in treasury_service.list_description_templates(self.company_id, self.direction)
        }

        # طبقِ آیتمِ ۷: روش‌هایِ سفارشیِ همین شرکت/جهت به فهرستِ کمبویِ روشِ
        # ردیف اضافه می‌شوند — برچسبشان در _METHOD_LABELS (دیکشنریِ
        # مشترک، اما چون کدشان بر اساسِ custom_method_id یکتاست، مشکلِ
        # هم‌پوشانیِ بینِ شرکت‌ها پیش نمی‌آید) هم ثبت می‌شود تا هرجایِ دیگرِ
        # فرم (عنوانِ دیالوگِ جزئیات، شرحِ خودکار) هم برچسبِ درست را ببیند.
        self._custom_method_codes = []
        for custom_method in treasury_service.list_custom_methods(self.company_id, self.direction, active_only=True):
            code = f"CUSTOM_{custom_method.custom_method_id}"
            _METHOD_LABELS[code] = custom_method.label
            self._custom_method_codes.append(code)

        self._reset_form()
        # طبقِ درخواستِ صریحِ آیتمِ ۴: هر بار این صفحه باز می‌شود، فوکوس
        # مستقیم رویِ طرفِ‌حساب می‌رود — هم‌الگو با تاریخ در فرمِ سندِ
        # حسابداری — تا کاربر بدونِ کلیکِ اضافه بتواند تایپ کند.
        self.account_combo.setFocus()
        self.account_combo.lineEdit().selectAll()

    def _on_currency_changed(self) -> None:
        """طبقِ درخواستِ صریح: انتخابِ ارزِ سند از بالایِ فرم — همه‌یِ
        ردیف‌ها (طرفِ‌حساب + روش‌ها) با همین یک ارز/نرخ ثبت می‌شوند.
        اگر ارزِ پایه انتخاب شود، نیازی به نرخ نیست (نرخ همیشه ۱ است)؛
        وگرنه آخرین نرخِ ثبت‌شده در تنظیمات (اگر باشد) خودکار پیشنهاد
        می‌شود، یا کاربر خودش دستی/با دکمه‌یِ «خودکار» وارد می‌کند."""
        selected_id = self.currency_combo.currentData()
        if selected_id is None:
            return
        is_base = selected_id == self._base_currency_id
        self.header_currency_id = None if is_base else selected_id
        self.rate_label.setVisible(not is_base)
        self.rate_field.setVisible(not is_base)
        self.rate_fetch_button.setVisible(not is_base)

        currency = self._currency_by_id.get(selected_id)
        self.currency_decimal_places = currency.decimal_places if currency else 0
        self.total_amount_field.setDecimals(self.currency_decimal_places)
        for row in self._method_rows:
            row.amount_field.setDecimals(self.currency_decimal_places)

        if is_base:
            self.header_exchange_rate = None
            self.rate_field.setText("")
        else:
            latest = None
            if self.company_id is not None:
                latest = currencies_service.get_latest_rate(self.company_id, selected_id, self.date_field.date())
            self.header_exchange_rate = latest
            self.rate_field.setText(numerals.format_amount(latest) if latest is not None else "")

    def _on_rate_changed(self) -> None:
        try:
            self.header_exchange_rate = numerals.parse_decimal(self.rate_field.text())
        except ValueError:
            self.header_exchange_rate = None

    def _on_fetch_rate(self) -> None:
        selected_id = self.currency_combo.currentData()
        if selected_id is None or selected_id == self._base_currency_id:
            return
        base_currency = self._currency_by_id.get(self._base_currency_id)
        target_currency = self._currency_by_id.get(selected_id)
        if base_currency is None or target_currency is None:
            return
        try:
            rate = currencies_service.fetch_live_rate(base_currency.iso_code, target_currency.iso_code)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        self.rate_field.setText(numerals.format_amount(rate))
        self._on_rate_changed()

    def _counterparty_label(self) -> str:
        detail_account_id = self.account_combo.currentData()
        return next((label for oid, label in self.account_options if oid == detail_account_id), "")

    def _counterparty_person_group_id(self) -> int | None:
        """طبقِ گزارشِ صریح: طرفِ‌حسابِ هدر (که همیشه یک تفصیلیِ اشخاص است)
        اگر خودش عضوِ همان گروهی باشد که معینِ یک ردیف الزامی‌اش کرده،
        دیگر نباید دوباره از کاربر پرسیده شود — این تابع همان گروهِ
        طرفِ‌حسابِ فعلی را برمی‌گرداند تا در _resolve_row_detail_source /
        _resolve_supplementary_person_detail بررسی شود."""
        if self.company_id is None:
            return None
        detail_account_id = self.account_combo.currentData()
        if detail_account_id is None:
            return None
        person = next(
            (p for p in dimensions_service.list_active_persons(self.company_id) if p.detail_account_id == detail_account_id),
            None,
        )
        return person.person_group_id if person is not None else None

    def _counterparty_payee_info(self) -> tuple[str, str, str]:
        """طبقِ درخواستِ صریحِ آیتمِ ۳: برایِ فرمِ چکِ پرداختی، نام/کدِملی/
        تلفنِ گیرنده دیگر دستی پرسیده نمی‌شود — از همین طرفِ‌حسابِ بالایِ
        فرم (که یک تفصیلیِ اشخاص است) خوانده می‌شود."""
        detail_account_id = self.account_combo.currentData()
        if self.company_id is None or detail_account_id is None:
            return "", "", ""
        return dimensions_service.get_person_contact_info(self.company_id, detail_account_id)

    def _update_balance_label(self) -> None:
        """طبقِ آیتمِ ۸: بعدِ هر تغییرِ طرفِ‌حساب، ماندهٔ فعلی‌اش (+ ماهیت)
        همین‌جا نمایش داده می‌شود."""
        detail_account_id = self.account_combo.currentData()
        if self.company_id is None or detail_account_id is None:
            self.balance_label.setText("")
            return
        balance, nature = treasury_service.get_counterparty_balance(self.company_id, detail_account_id)
        self.balance_label.setText(
            f"ماندهٔ طرفِ‌حساب: {numerals.format_money(balance, self.currency_decimal_places)} ({nature})"
        )

    def _open_counterparty_ledger(self) -> None:
        """طبقِ آیتمِ ۹: بازکردنِ مستقیمِ گزارشِ معینِ همین طرفِ‌حساب."""
        detail_account_id = self.account_combo.currentData()
        if self._main_window is None or self.company_id is None or detail_account_id is None:
            return
        label = self._counterparty_label()
        self._main_window.open_screen(
            "REPORTS_ACCOUNT_LEDGER",
            then=lambda screen: screen.show_ledger_for_detail(detail_account_id, label),
        )

    def _open_link_invoices_dialog(self) -> None:
        """طبقِ درخواستِ صریح: فهرستِ فاکتورهایِ بازِ همین طرفِ‌حساب (بر
        اساسِ جهتِ سند -- دریافت یعنی فاکتورِ فروش، پرداخت یعنی فاکتورِ
        خرید) را نشان می‌دهد؛ بعدِ تاییدِ کاربر، مبلغ‌هایِ واردشده در
        self._settle_invoices نگه داشته می‌شوند تا _save() خودکار آن‌ها
        را تسویه کند -- دقیقاً همان مکانیزمِ prefill_for_invoice، فقط از
        همین‌جا (نه از فرمِ تسویه) شروع می‌شود."""
        detail_account_id = self.account_combo.currentData()
        if self.company_id is None or detail_account_id is None:
            theme.set_status_label(self.status_label, "ابتدا طرفِ‌حساب را انتخاب کنید.", ok=False)
            return
        invoice_type = _INVOICE_TYPE_BY_DIRECTION[self.direction]
        statuses = settlements_service.list_unsettled_invoices(self.company_id, invoice_type)
        docs_by_id = {}
        matching = []
        for status in statuses:
            try:
                doc, _lines = documents_service.get_document(status.document_id, self.company_id)
            except ValueError:
                continue
            if doc is not None and doc.counterparty_detail_account_id == detail_account_id:
                docs_by_id[status.document_id] = doc
                matching.append(status)
        if not matching:
            QMessageBox.information(self, "فاکتورهایِ باز", "این طرفِ‌حساب فاکتورِ بازِ تسویه‌نشده‌ای ندارد.")
            return
        dialog = _LinkInvoicesDialog(self, matching, docs_by_id, self.direction)
        if dialog.exec() != QDialog.Accepted:
            return
        entries = dialog.result_entries()
        if not entries:
            return
        self._settle_invoices = list(entries.items())
        total = sum(entries.values(), decimal.Decimal(0))
        self.total_amount_field.setValue(float(total))
        if not self.description_field.text().strip():
            remaining_by_id = {status.document_id: status.remaining_amount for status in matching}
            entries_info = [
                (docs_by_id[doc_id].document_no, remaining_by_id[doc_id], amount) for doc_id, amount in entries.items()
            ]
            self.description_field.setText(
                _describe_invoice_settlement(self.direction, entries_info, self._counterparty_label())
            )
        self._update_rows_summary()
        theme.set_status_label(
            self.status_label,
            f"{numerals.to_persian_digits(str(len(entries)))} فاکتور لینک شد — جمعِ مبلغ "
            f"({numerals.format_money(total, self.currency_decimal_places)}) در بالایِ فرم پر شد.",
            ok=True,
        )

    def _quick_add_counterparty(self) -> None:
        """طبقِ توضیحِ کاربر: منظور از این دکمه‌یِ میان‌بر، بازکردنِ خودِ
        فرمِ «تعریفِ تفصیلی» (GL_DIM) بود — نه یک دیالوگِ سبکِ جداگانه.
        وقتی کاربر از آن‌جا به این فرم برگردد، refresh() (که خودِ ناوبری
        صدا می‌زند) کمبویِ طرفِ‌حساب را از نو می‌سازد و تفصیلیِ تازه‌ساخته
        خودکار در آن ظاهر می‌شود."""
        if self.company_id is None:
            theme.set_status_label(self.status_label, "ابتدا یک شرکت را انتخاب کنید.", ok=False)
            return
        if self._main_window is None:
            return
        self._main_window.open_screen("GL_DIM")

    def _build_counterparty_options(self) -> list[tuple[int, str]]:
        """طبقِ درخواستِ صریح: فقط تفصیلی‌هایِ گروه‌هایی که در «انواعِ سندِ
        دریافت/پرداخت» (تنظیماتِ سیستم/تبِ خزانه‌داری) نگاشته شده‌اند این‌جا
        پیشنهاد می‌شوند — نه معین، نه بقیه‌یِ تفصیلی‌ها؛ و فقط تفصیلی‌هایِ
        سطحِ آخر (برگ‌هایِ سلسله‌مراتب)، نه گروه‌هایِ والد."""
        self._counterparty_index = {}
        mappings = treasury_service.list_counterparty_mappings(self.company_id, self.direction)
        person_mapping_by_group = {m.person_group_id: m.account_id for m in mappings if m.person_group_id is not None}
        dim_mapping_by_type = {m.dimension_type_id: m.account_id for m in mappings if m.dimension_type_id is not None}

        options: list[tuple[int, str]] = []
        if person_mapping_by_group:
            person_type_id = dimensions_service.get_person_dimension_type_id(self.company_id)
            for d in dimensions_service.list_leaf_detail_accounts(self.company_id, person_type_id):
                if d.person_group_id in person_mapping_by_group:
                    account_id = person_mapping_by_group[d.person_group_id]
                    self._counterparty_index[d.detail_account_id] = (account_id, person_type_id)
                    options.append((d.detail_account_id, _detail_option_label(d)))
        for dimension_type_id, account_id in dim_mapping_by_type.items():
            for d in dimensions_service.list_leaf_detail_accounts(self.company_id, dimension_type_id):
                self._counterparty_index[d.detail_account_id] = (account_id, dimension_type_id)
                options.append((d.detail_account_id, _detail_option_label(d)))
        return options

    def _on_account_changed(self, _index: int) -> None:
        while self.detail_container.count():
            child = self.detail_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._detail_combos = {}
        self._update_balance_label()

        if self.company_id is None:
            return

        detail_account_id = self.account_combo.currentData()
        account_id: int | None = None
        skip_dimension_type_id: int | None = None
        if detail_account_id is not None and detail_account_id in self._counterparty_index:
            account_id, skip_dimension_type_id = self._counterparty_index[detail_account_id]

        required = dimensions_service.get_required_dimensions_for_account(account_id) if account_id is not None else []
        required_type_ids = {r.dimension_type_id for r in required if r.dimension_type_id != skip_dimension_type_id}

        # طبقِ درخواستِ صریح: این کمبوها (مرکزِ هزینه/پروژه) افقی و جلویِ
        # خودِ طرفِ‌حساب می‌آیند — نه یک ردیفِ جداگانه؛ برایِ همین به‌جایِ
        # ویجت‌بندیِ عمودیِ قبلی، مستقیم به‌ترتیب در detail_containerِ افقی
        # اضافه می‌شوند و زنجیره‌یِ Enter از رویِ همین ترتیب ساخته می‌شود.
        combos: list[QComboBox] = []

        # طبقِ گزارشِ صریح («مرکزِ هزینه/پروژه در هدر مخفی‌اند تا وقتی
        # تفصیلی انتخاب شود»): این دو همیشه ساخته و نمایش داده می‌شوند —
        # فقط enable/disable می‌شوند (فعال اگر معینِ طرفِ‌حسابِ انتخاب‌شده
        # واقعاً همان بُعد را الزامی کرده باشد، وگرنه غیرفعال).
        for code in _HEADER_SHARED_DIMENSION_CODES:
            type_id = dimensions_service.get_specialized_dimension_type_id(self.company_id, code)
            if type_id is None:
                continue
            label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(code, code)
            self.detail_container.addWidget(QLabel(label))
            options = dimensions_service.list_leaf_detail_accounts(self.company_id, type_id)
            combo = _make_searchable_combo([(d.detail_account_id, _detail_option_label(d)) for d in options])
            combo.setMaximumWidth(160)
            combo.setEnabled(type_id in required_type_ids)
            self.detail_container.addWidget(combo)
            self._detail_combos[type_id] = combo
            combos.append(combo)

        for required_dim in required:
            if required_dim.dimension_type_id == skip_dimension_type_id:
                continue  # این بُعد از طریقِ تفصیلیِ طرفِ‌حسابِ انتخاب‌شده حل شده
            if required_dim.code in _HEADER_SHARED_DIMENSION_CODES:
                continue  # مرکزِ هزینه/پروژه از قبل بالا ساخته شدند
            label = "تفصیلیِ اشخاص" if required_dim.code == dimensions_service.PERSON_DIMENSION_CODE else dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(required_dim.code, required_dim.code)
            self.detail_container.addWidget(QLabel(label))
            combo = _make_searchable_combo([(d.detail_account_id, _detail_option_label(d)) for d in required_dim.detail_accounts])
            combo.setMaximumWidth(160)
            self.detail_container.addWidget(combo)
            self._detail_combos[required_dim.dimension_type_id] = combo
            combos.append(combo)

        # زنجیره‌یِ Enter از میانِ همین کمبوها تا تاریخ — فقط کمبوهایِ
        # *فعال* در زنجیره می‌مانند، وگرنه Enter ممکن است فوکوس را به یک
        # فیلدِ غیرفعال/غیرقابل‌دریافتِ فوکوس بفرستد و ناوبری گیر کند.
        enabled_combos = [c for c in combos if c.isEnabled()]
        for combo, next_combo in zip(enabled_combos, enabled_combos[1:]):
            combo.lineEdit().returnPressed.connect(next_combo.setFocus)
        if enabled_combos:
            enabled_combos[-1].lineEdit().returnPressed.connect(self.date_field.setFocus)

        # طبقِ درخواستِ صریح: طرفِ‌حساب در متنِ خودکارِ شرحِ همه‌یِ ردیف‌ها
        # به‌کار می‌رود — با تغییرش، شرحِ همه‌یِ ردیف‌ها هم به‌روز شود.
        for row in self._method_rows:
            row._regenerate_description()

    def _covered_dimension_type_ids(self) -> set[int]:
        """طبقِ اصلاحِ آیتمِ ۱: چون مرکزِ هزینه/پروژه حالا همیشه در
        _detail_combos هستند (حتی وقتی غیرفعال/نامرتبط)، فقط بُعدهایِ
        *واقعاً فعال* «پوشش‌یافته» حساب می‌شوند — وگرنه یک ترکیبِ
        غیرفعال به‌اشتباه مانعِ پرسیدنِ همان بُعد در دیالوگِ جزئیاتِ یک
        ردیفِ دیگر می‌شود."""
        return {type_id for type_id, combo in self._detail_combos.items() if combo.isEnabled()}

    def _on_account_return(self) -> None:
        # طبقِ اصلاحِ آیتمِ ۱: مرکزِ هزینه/پروژه حالا همیشه در _detail_combos
        # هستند، حتی وقتی غیرفعال/نامرتبط‌اند — پس فقط بینِ کمبوهایِ *فعال*
        # باید فوکوس رفت، وگرنه Enter رویِ یک فیلدِ خاکستری/غیرقابل‌استفاده
        # می‌ایستد.
        first_combo = next((c for c in self._detail_combos.values() if c.isEnabled()), None)
        if first_combo is not None:
            first_combo.setFocus()
            first_combo.lineEdit().selectAll()
        else:
            self.date_field.setFocus()

    def _add_row(self) -> _MethodRow:
        row = _MethodRow(self)
        row_index = self.table.rowCount()
        self.table.insertRow(row_index)
        self.table.setCellWidget(row_index, 0, row.method_combo)
        self.table.setCellWidget(row_index, 1, row.amount_cell)
        self.table.setCellWidget(row_index, 2, row.description_field)
        self.table.setCellWidget(row_index, 3, row.details_button)
        self.table.setCellWidget(row_index, 4, row.installment_link_button)
        self.table.setCellWidget(row_index, 5, row.remove_button)
        self._method_rows.append(row)
        self._update_rows_summary()
        return row

    def _remove_row(self, row: _MethodRow) -> None:
        if row not in self._method_rows:
            return
        row_index = self._method_rows.index(row)
        self.table.removeRow(row_index)
        self._method_rows.pop(row_index)
        self._update_rows_summary()

    def _rows_total(self) -> decimal.Decimal:
        """جمعِ سادهِ مبلغِ همه‌یِ ردیف‌هایِ فعلی — هم توسطِ _remaining_amount
        و هم توسطِ Spaceِ فیلدِ مبلغِ هدر (وقتی خالی است) استفاده می‌شود."""
        return sum(
            (decimal.Decimal(str(row.amount_field.value())) for row in self._method_rows), decimal.Decimal(0)
        )

    def _remaining_amount(self) -> decimal.Decimal:
        """اختلافِ جمعِ مبلغِ هدر (دریافتی/پرداختی) با جمعِ ردیف‌هایِ فعلی
        — یعنی «چقدر هنوز تخصیص‌نیافته باقی مانده». طبقِ آیتمِ ۶: با
        Spaceِ فیلدِ مبلغِ یک ردیف کپی می‌شود."""
        header_total = decimal.Decimal(str(self.total_amount_field.value()))
        return header_total - self._rows_total()

    def _update_rows_summary(self) -> None:
        """طبقِ درخواستِ صریح: جمعِ زنده‌یِ ردیف‌ها و اختلافش با جمعِ مبلغِ
        هدر، همان‌جایِ هدر نمایش داده شود — هم برایِ دریافت هم پرداخت."""
        rows_total = self._rows_total()
        diff = self._remaining_amount()
        total_word = "دریافتی" if self.direction == "RECEIPT" else "پرداختی"
        theme.set_status_label(
            self.rows_summary_label,
            f"جمعِ ردیف‌ها: {numerals.format_money(rows_total, self.currency_decimal_places)}    —    "
            f"اختلاف با جمعِ {total_word}: {numerals.format_money(diff, self.currency_decimal_places)}",
            ok=(diff == 0),
        )
        header_total = decimal.Decimal(str(self.total_amount_field.value()))
        self.summary_cards.set_value("total", numerals.format_money(header_total, self.currency_decimal_places))
        self.summary_cards.set_value("rows_total", numerals.format_money(rows_total, self.currency_decimal_places))
        self.summary_cards.set_value("diff", numerals.format_money(diff, self.currency_decimal_places))
        self.summary_cards.set_role("diff", "success" if diff == 0 else "danger")
        self._update_ras_label()

    def _update_ras_label(self) -> None:
        """طبقِ آیتمِ ۶ (و بسطِ آن طبقِ درخواستِ صریحِ بعدی: «راسِ چک را با
        مبالغِ دریافتی با هم محاسبه کند»): راسِ وزنیِ همه‌یِ چک‌هایِ واردشده
        (بر اساسِ سررسیدِ واقعیِ هرکدام) به‌همراهِ مبلغِ ردیف‌هایِ نقدی
        (که سررسیدشان همین امروز است) — با هم، یک راسِ واحد."""
        today = datetime.date.today()
        entries: list[tuple[decimal.Decimal, datetime.date]] = []
        for row in self._method_rows:
            method = row.method_combo.currentData()
            if method == "CHECK":
                entries.extend((c["amount"], c["due_date"]) for c in (row.details.get("checks") or []))
            elif method == "CASH":
                try:
                    cash_amount = decimal.Decimal(str(row.amount_field.value()))
                except (ValueError, decimal.InvalidOperation):
                    cash_amount = decimal.Decimal(0)
                if cash_amount > 0:
                    entries.append((cash_amount, today))
        if not entries:
            self.ras_label.setText("")
            return
        ras_date, total = treasury_service.compute_check_ras(entries, base_date=today)
        self.ras_label.setText(
            f"راسِ چک+نقد: {numerals.format_jalali_date(ras_date)}    —    "
            f"جمعِ مبلغ: {numerals.format_money(total, self.currency_decimal_places)}"
        )

    def _focus_first_row_method(self) -> None:
        if not self._method_rows:
            self._add_row()
        self.table.setCurrentCell(0, 0)
        self._method_rows[0].method_combo.setFocus()

    def _focus_next_row_after(self, row: _MethodRow) -> None:
        """زنجیره‌ی Enter: شرح -> ردیفِ بعدی (اگر نبود، تازه ساخته می‌شود)
        -> روشِ همان ردیف — هم‌الگو با focus_next_row_afterِ
        journal_entry.py. اگر ردیفِ فعلی هنوز ناقص است (مبلغ صفر)، Enterِ
        تصادفی ردیفِ تازه‌ای نمی‌سازد."""
        if row.to_method_line() is None:
            return
        if row is self._method_rows[-1]:
            target = self._add_row()
        else:
            target = self._method_rows[self._method_rows.index(row) + 1]
        self.table.setCurrentCell(self._method_rows.index(target), 0)
        target.method_combo.setFocus()

    def _reset_form(self) -> None:
        self.table.setRowCount(0)
        self._method_rows = []
        self._add_row()
        self.date_field.setDate(datetime.date.today())
        self.description_field.clear()
        self.total_amount_field.setValue(0)
        self.account_combo.setCurrentIndex(0)
        base_index = self.currency_combo.findData(self._base_currency_id)
        if base_index >= 0:
            self.currency_combo.setCurrentIndex(base_index)
        self.status_label.setText("")
        self._settle_invoices = []
        self._update_rows_summary()

    def prefill_for_invoice(
        self, counterparty_id: int | None, amount: decimal.Decimal, description: str,
        settle_invoices: list[tuple[int, decimal.Decimal]] | None = None,
    ) -> None:
        """طبقِ درخواستِ صریح: بعدِ ثبتِ نهاییِ فاکتورِ فروش/خرید، همین فرم
        (دریافت/پرداخت) با طرفِ‌حساب و مبلغِ همان فاکتور باز شود — کاربر
        فقط روشِ پرداخت (نقد/بانک/چک) را انتخاب و مبلغ را تایید می‌کند
        (یا با اسپیس در فیلدِ ردیف، مبلغِ بالای فرم را کپی می‌کند).

        اگر settle_invoices داده شود (طبقِ درخواستِ صریح: بازکردنِ همین فرم
        مستقیماً از «مدیریتِ تسویه‌یِ فاکتورها» -- حتی برایِ چند فاکتورِ
        هم‌زمانِ یک طرفِ‌حساب)، بعدِ ثبتِ موفقِ همین سند، خودکار به‌عنوانِ
        تسویه‌یِ همه‌یِ آن فاکتورها (هرکدام با مبلغِ خودش از همین فهرست،
        نه لزوماً amountِ سرِ فرم) هم ثبت می‌شود -- دیگر نیازی به دوباره
        رفتن به فرمِ تسویه و انتخابِ دستیِ آن‌ها نیست."""
        self._reset_form()
        if counterparty_id is not None:
            index = self.account_combo.findData(counterparty_id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
        self.total_amount_field.setValue(float(amount))
        self.description_field.setText(description)
        self._settle_invoices = list(settle_invoices) if settle_invoices else []
        self._update_rows_summary()

    def _compose_description(self) -> str:
        """طبقِ درخواستِ صریح: شرحِ سمتِ بستانکارِ سندِ دریافت خودکار
        بشود: «دریافت از {طرفِ‌حساب} - {روش‌هایِ استفاده‌شده} - {شرحِ
        دستیِ کاربر}» — فقط برایِ دریافت (طبقِ چارچوبِ همین درخواست)."""
        manual = self.description_field.text().strip()
        if self.direction != "RECEIPT":
            return manual
        counterparty_label = self._counterparty_label()
        method_labels: list[str] = []
        for row in self._method_rows:
            line = row.to_method_line()
            if line is None:
                continue
            label = _METHOD_LABELS.get(line.method, line.method)
            if label not in method_labels:
                method_labels.append(label)
        parts: list[str] = []
        if counterparty_label:
            parts.append(f"دریافت از {counterparty_label}")
        if method_labels:
            parts.append(" و ".join(method_labels))
        if manual:
            parts.append(manual)
        return " - ".join(parts) if parts else manual

    def _save(self) -> None:
        if self.company_id is None or session.current_user is None:
            theme.set_status_label(self.status_label, "ابتدا یک شرکت را انتخاب کنید.", ok=False)
            return
        detail_account_id = self.account_combo.currentData()
        if detail_account_id is None or detail_account_id not in self._counterparty_index:
            theme.set_status_label(self.status_label, "طرفِ حساب (تفصیلی) را انتخاب کنید.", ok=False)
            return
        account_id, resolved_dimension_type_id = self._counterparty_index[detail_account_id]
        counterparty_details = {resolved_dimension_type_id: detail_account_id}
        counterparty_details.update(
            {
                dimension_type_id: combo.currentData()
                for dimension_type_id, combo in self._detail_combos.items()
                if combo.isEnabled() and combo.currentData() is not None
            }
        )
        method_lines = [ln for row in self._method_rows if (ln := row.to_method_line()) is not None]
        if not method_lines:
            theme.set_status_label(self.status_label, "حداقل یک ردیفِ روش (با مبلغِ مثبت) لازم است.", ok=False)
            return

        total_word = "دریافتی" if self.direction == "RECEIPT" else "پرداختی"
        header_total = decimal.Decimal(str(self.total_amount_field.value()))
        if header_total <= 0:
            theme.set_status_label(self.status_label, f"جمعِ مبلغِ {total_word} را در هدر وارد کنید.", ok=False)
            return
        rows_total = sum((ln.amount for ln in method_lines), decimal.Decimal(0))
        if rows_total != header_total:
            theme.set_status_label(
                self.status_label,
                f"جمعِ ردیف‌ها ({numerals.format_money(rows_total, self.currency_decimal_places)}) "
                f"با مبلغِ {total_word}ِ هدر "
                f"({numerals.format_money(header_total, self.currency_decimal_places)}) برابر نیست.",
                ok=False,
            )
            return

        # طبقِ درخواستِ صریح: «دریافتِ ارزی هم داشته باشیم» — اگر ارزِ
        # غیرِپایه انتخاب شده، نرخ باید مثبت باشد (وگرنه تبدیل به ارزِ
        # پایه برایِ تراز کردنِ سند ممکن نیست).
        if self.header_currency_id is not None and (
            self.header_exchange_rate is None or self.header_exchange_rate <= 0
        ):
            theme.set_status_label(self.status_label, "نرخِ ارز را وارد کنید.", ok=False)
            return

        try:
            result = treasury_service.create_treasury_voucher(
                self.company_id,
                session.current_user.user_id,
                self.direction,
                account_id,
                counterparty_details,
                self.date_field.date(),
                self._compose_description(),
                method_lines,
                currency_id=self.header_currency_id,
                exchange_rate=self.header_exchange_rate,
            )
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return

        # طبقِ آیتمِ ۵: داده‌یِ رسید باید پیش از _reset_form (که همه‌یِ
        # فیلدها/ردیف‌ها را پاک می‌کند) برداشته شود.
        receipt_row_lines = [
            row.description_field.text().strip()
            for row in self._method_rows
            if row.to_method_line() is not None and row.description_field.text().strip()
        ]
        receipt_counterparty_label = self._counterparty_label()
        receipt_date_text = self.date_field.text()
        receipt_manual_description = self.description_field.text().strip()
        # طبقِ درخواستِ صریح («از فرمِ تسویه‌یِ فاکتورها بازشود و رفرنس
        # بدهد» + «مبلغِ دریافتی برایِ چند فاکتورِ هم‌زمان»): پیش از reset
        # (که این فهرست را هم پاک می‌کند) نگه داشته می‌شود -- اگر از
        # commercial_settlement.py برایِ همین منظور باز شده باشد، بعدِ
        # ثبتِ موفقِ سند، خودکار تسویه‌یِ همه‌یِ آن فاکتورها (هرکدام با
        # مبلغِ خودش) هم ثبت می‌شود.
        settle_invoices = self._settle_invoices
        settlement_errors: list[str] = []
        for invoice_document_id, invoice_amount in settle_invoices:
            try:
                settlements_service.allocate_settlement(
                    self.company_id, invoice_document_id, result.journal_entry_id,
                    self.date_field.date(), invoice_amount, session.current_user.user_id,
                    description=self._compose_description(),
                )
            except ValueError as exc:
                settlement_errors.append(f"#{invoice_document_id}: {exc}")

        self._reset_form()
        success_message = f"سند با شماره‌ی موقتِ {numerals.to_persian_digits(str(result.temporary_no))} ثبت شد."
        if settle_invoices:
            if not settlement_errors:
                success_message += (
                    " تسویه‌یِ فاکتورِ مربوطه هم ثبت شد." if len(settle_invoices) == 1
                    else f" تسویه‌یِ هر {len(settle_invoices)} فاکتور هم ثبت شد."
                )
            else:
                success_message += f" (هشدار: سند ثبت شد، اما این تسویه‌ها وصل نشدند -- {'؛ '.join(settlement_errors)})"
        theme.set_status_label(self.status_label, success_message, ok=(not settlement_errors))
        _prompt_and_print_receipt(
            self,
            self.direction,
            temporary_no=result.temporary_no,
            date_text=receipt_date_text,
            counterparty_label=receipt_counterparty_label,
            total_amount=header_total,
            decimal_places=self.currency_decimal_places,
            row_lines=receipt_row_lines,
            manual_description=receipt_manual_description,
        )


# --- آیتمِ ۵: رسیدِ چاپیِ دریافت/پرداخت -------------------------------------
# طبقِ درخواستِ صریح («رسید دریافت و پرداخت برای فرمها درست بشه که بعد از
# تایید سوال کنه که نسخه چاپی یا pdf بده»، با نمونه‌یِ تصویریِ ضمیمه‌شده):
# این یک گزارشِ جدولیِ عمومی نیست (بر خلافِ report_export.py که برایِ
# جدول‌هایِ چندصفحه‌ای با هدر/فوترِ تکرارشونده ساخته شده) — یک برگه‌یِ
# روایی/تک‌صفحه‌ایِ کوتاه است: جمله‌یِ «مبلغِ … از/به … دریافت/پرداخت شد»
# + شرحِ خودکارِ هر ردیفِ روش (که از قبل در جدولِ فرم ساخته شده) + پایِ
# امضایِ چهارستونی. برایِ همین به‌جایِ بازاستفاده از _paint_report، یک
# QTextDocument سادهِ تک‌صفحه‌ای مستقیماً چاپ/PDF می‌شود.
def _receipt_font_family() -> str:
    try:
        return get_font_family()
    except Exception:
        return "Tahoma"


def _escape_receipt_html(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_receipt_html(
    *,
    direction: str,
    company_name: str,
    temporary_no: int,
    date_text: str,
    time_text: str,
    counterparty_label: str,
    total_amount: decimal.Decimal,
    decimal_places: int,
    row_lines: list[str],
    manual_description: str,
    font_family: str,
) -> str:
    esc = _escape_receipt_html
    noun = "دریافت" if direction == "RECEIPT" else "پرداخت"
    verb = "دریافت شد" if direction == "RECEIPT" else "پرداخت شد"
    preposition = "از" if direction == "RECEIPT" else "به"
    signer_label = "دریافت‌کننده" if direction == "RECEIPT" else "پرداخت‌کننده"
    total_text = numerals.format_money(total_amount, decimal_places)

    rows_html = "".join(f"<div style='margin:5px 0;'>• {esc(line)}</div>" for line in row_lines)
    manual_html = (
        f"<div style='margin-top:12px;'><b>توضیحات:</b> {esc(manual_description)}</div>"
        if manual_description
        else ""
    )
    signature_cols = ["تنظیم‌کننده", "مدیرِ مالی", "مدیرِعامل", signer_label]
    signature_cells = "".join(
        f"<td style='width:25%; text-align:center; padding-top:50px; "
        f"border-top:1px solid #888;'>{esc(col)}</td>"
        for col in reversed(signature_cols)
    )
    return f"""
    <html dir="rtl"><head><meta charset="utf-8"></head>
    <body style="font-family:'{font_family}', Tahoma, sans-serif; font-size:11pt;">
      <div style="text-align:center; font-size:13pt; font-weight:bold;">{esc(company_name)}</div>
      <div style="text-align:center; font-size:12pt; font-weight:bold; margin:6px 0 16px 0;">
        رسیدِ {noun}
      </div>
      <table width="100%" style="margin-bottom:16px;">
        <tr>
          <td style="text-align:left;">ساعت: {esc(time_text)}</td>
          <td style="text-align:center;">تاریخ: {esc(date_text)}</td>
          <td style="text-align:right;">شماره‌یِ سند: {numerals.to_persian_digits(str(temporary_no))}</td>
        </tr>
      </table>
      <div style="margin-bottom:10px;">
        مبلغ: <b>{total_text}</b> ریال {preposition} حساب/صورتحسابِ
        <b>{esc(counterparty_label)}</b> بشرحِ زیر {verb}:
      </div>
      {rows_html}
      {manual_html}
      <table width="100%" style="margin-top:70px;">
        <tr>{signature_cells}</tr>
      </table>
    </body></html>
    """


def _print_receipt_document(parent: QWidget, html: str) -> None:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter)
    doc = QTextDocument()
    doc.setHtml(html)
    preview = QPrintPreviewDialog(printer, parent)
    preview.paintRequested.connect(lambda p: doc.print_(p))
    preview.showMaximized()
    preview.exec()


def _export_receipt_pdf_document(parent: QWidget, html: str, default_filename: str) -> None:
    path, _filter = QFileDialog.getSaveFileName(parent, "ذخیره‌یِ PDF", default_filename, "PDF (*.pdf)")
    if not path:
        return
    if not path.lower().endswith(".pdf"):
        path += ".pdf"
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter)
    printer.setOutputFileName(path)
    doc = QTextDocument()
    doc.setHtml(html)
    doc.print_(printer)
    QMessageBox.information(parent, "خروجیِ PDF", "فایلِ PDF با موفقیت ساخته شد.")


def _prompt_and_print_receipt(
    parent: QWidget,
    direction: str,
    *,
    temporary_no: int,
    date_text: str,
    counterparty_label: str,
    total_amount: decimal.Decimal,
    decimal_places: int,
    row_lines: list[str],
    manual_description: str,
) -> None:
    """طبقِ آیتمِ ۵: بعدِ ثبتِ موفقِ سند، رسیدِ دریافت/پرداخت (برگه‌یِ
    روایی، نه گزارشِ جدولی) پیشنهاد می‌شود؛ کاربر بینِ چاپ، PDF، یا
    انصراف انتخاب می‌کند."""
    company_name = session.current_company.display_name if session.current_company else ""
    time_text = numerals.to_persian_digits(datetime.datetime.now().strftime("%H:%M"))
    html = _build_receipt_html(
        direction=direction,
        company_name=company_name,
        temporary_no=temporary_no,
        date_text=date_text,
        time_text=time_text,
        counterparty_label=counterparty_label,
        total_amount=total_amount,
        decimal_places=decimal_places,
        row_lines=row_lines,
        manual_description=manual_description,
        font_family=_receipt_font_family(),
    )
    box = QMessageBox(parent)
    box.setWindowTitle("رسیدِ سند")
    box.setText("سند ثبت شد. رسیدِ آن چاپ یا به PDF ذخیره شود؟")
    print_button = box.addButton("چاپ", QMessageBox.ActionRole)
    pdf_button = box.addButton("PDF", QMessageBox.ActionRole)
    box.addButton("انصراف", QMessageBox.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is print_button:
        _print_receipt_document(parent, html)
    elif clicked is pdf_button:
        _export_receipt_pdf_document(
            parent, html, f"رسید-{numerals.to_persian_digits(str(temporary_no))}.pdf"
        )
