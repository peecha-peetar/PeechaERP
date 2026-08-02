"""فرمِ واحدِ دریافت/پرداختِ چندروشی — یک طرف‌حساب + چند ردیفِ روش (نقد/
بانک/چک/تخفیف/کالابرگ/بن)، هرکدام طبقِ نگاشتِ تنظیماتِ خزانه‌داری به
حسابِ خودش می‌رود و همه در یک سندِ حسابداریِ واحد ثبت می‌شوند
(services/treasury.create_treasury_voucher). طبقِ درخواستِ صریح: «دریافت
از آقایِ ایکس مبلغِ ۲۰۰۰ که در فرم مشخص بشه نقدی یا بانک یا چک یا در
قالبِ تخفیف»."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import treasury as treasury_service
from peecha.ui import theme
from peecha.ui.screens.journal_entry import _AmountField, _fill_options, _make_searchable_combo
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit

_METHOD_LABELS = {
    "CASH": "نقدی",
    "BANK": "بانکی",
    "CHECK": "چک",
    "DISCOUNT": "تخفیف",
    "GOODS_COUPON": "کالابرگ",
    "VOUCHER": "بن",
    "NETTING": "تهاتر",
    "CHECK_DISBURSEMENT": "پرداخت با چکِ دریافتی (خرجِ چک)",
}
_RECEIPT_METHOD_CODES = ["CASH", "BANK", "CHECK", "DISCOUNT", "GOODS_COUPON", "VOUCHER", "NETTING"]
_PAYMENT_METHOD_CODES = ["CASH", "BANK", "CHECK", "DISCOUNT", "CHECK_DISBURSEMENT", "NETTING"]
# طبقِ درخواستِ صریح: تهاتر هم مثلِ نقد/بانک/تخفیف/کالابرگ/بن، تفصیلیِ
# احتمالیِ خودش را (از رویِ نگاشتِ تنظیمات) نشان می‌دهد — پس دیگر همیشه از
# دیالوگِ جزئیات معاف نیست؛ اگر برایِ آن معینی تفصیلی/بُعدِ الزامی نداشت،
# _open_details خودش تشخیص می‌دهد و دیالوگِ خالی باز نمی‌کند.
_METHODS_WITHOUT_DETAILS = ()
# روش‌هایی که تفصیلیِ ردیفشان صرفاً از رویِ نگاشتِ معینِ تنظیمات تعیین
# می‌شود (نه فیلدِ دیگری مثلِ سریالِ بن) — اگر پیش‌تخصیص یا گزینه‌ای نباشد،
# اصلاً دیالوگ باز نمی‌شود.
_MAPPING_ONLY_DETAIL_METHODS = ("CASH", "BANK", "DISCOUNT", "GOODS_COUPON", "NETTING")
# نوع‌بُعدهایی که تفصیلیِ نقد/بانک معمولاً از رویِ آن‌ها ساخته می‌شوند —
# فقط برایِ برچسبِ فیلد؛ خودِ فهرستِ گزینه‌ها همیشه از رویِ بُعدِ الزامیِ
# واقعیِ همان معینِ نگاشته‌شده گرفته می‌شود (نه این کدها به‌طورِ مستقیم).


class _EnterComboBox(QComboBox):
    """کمبویِ غیرِقابلِ‌ویرایشِ روش — Enter به‌جایِ بازکردنِ popup، سیگنالِ
    enterPressed می‌فرستد تا زنجیره‌یِ ناوبریِ کیبوردیِ ردیف را کنترل کند."""

    enterPressed = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 — نامِ متدِ Qt
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.enterPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


# طبقِ درخواستِ صریح: مرکزِ هزینه/پروژه ویژگیِ خودِ رویدادِ مالی‌اند، نه
# طرفِ‌حساب یا روش — همان مقداری که در هدرِ فرم انتخاب شده باید برایِ همه‌ی
# ردیف‌ها به‌کار رود (create_treasury_voucher خودش این را با shared_details
# تضمین می‌کند)؛ پس اگر بُعدِ الزامیِ معینِ یک روش مرکزِ هزینه/پروژه باشد،
# دیالوگِ آن روش دوباره از کاربر نمی‌پرسد.
_HEADER_SHARED_DIMENSION_CODES = (dimensions_service.COST_CENTER_CODE, dimensions_service.PROJECT_CODE)


def _resolve_row_detail_source(
    company_id: int, mapping_key: str, covered_dimension_type_ids: set[int] | None = None
) -> tuple[int | None, tuple[int, str] | None, str, list]:
    """منبعِ تفصیلیِ یک ردیف (نقد/بانک/تخفیف/کالابرگ/بن/تهاتر) را مشخص
    می‌کند — به‌ترتیبِ اولویت:

    ۱) تفصیلیِ اختصاصیِ از‌پیش‌تخصیص‌یافته در تنظیماتِ خزانه‌داری (طبقِ
       درخواستِ صریح: «در هر ردیف از نوع سند غیر از کد معین بتوان کد
       تفصیلی خاص هم تخصیص داد») — اگر باشد، دیگر از کاربر پرسیده نمی‌شود.
    ۲) بُعدِ الزامیِ واقعیِ همان معینِ نگاشته‌شده (get_required_dimensions_for_account)
       — اگر معین چند بُعدِ الزامی داشته باشد (مثلاً هم مرکزِ هزینه هم یک
       نوع‌بُعدِ اختصاصیِ دیگر)، اولین بُعدی که «مرکزِ هزینه/پروژه‌یِ
       پوشش‌یافته‌توسطِ‌هدر» نباشد انتخاب می‌شود — نه صرفاً اولین موردِ
       فهرست؛ وگرنه بُعدِ اختصاصیِ کالابرگ/بن هیچ‌وقت دیده نمی‌شد چون
       مرکزِ هزینه (اگر اول باشد و پوشش‌یافته باشد) کلِ معین را
       «بدونِ‌تفصیلی» جلوه می‌داد.
    ۳) اگر معین هیچ بُعدِ الزامی‌ای هم نداشته باشد (مثلاً تخفیف که هنوز
       نوع‌بُعدی رویش تنظیم نشده) — به‌جایِ این‌که هیچ‌جا نتوان تفصیلی وارد
       کرد، جستجویِ آزاد رویِ همه‌یِ تفصیلی‌هایِ برگِ شرکت پیشنهاد می‌شود
       («اگر تفصیلی تخصیص ندهیم از سند انتخاب کنیم»).

    خروجی: (account_id, پیش‌تخصیص (id, برچسب) یا None، برچسبِ فیلد، فهرستِ گزینه‌ها)."""
    account_id, preset_detail_id = treasury_service.get_account_mapping_with_detail(company_id, mapping_key)
    if account_id is None:
        return None, None, "", []
    if preset_detail_id is not None:
        preset_row = next(
            (d for d in dimensions_service.list_all_leaf_detail_accounts(company_id) if d.detail_account_id == preset_detail_id),
            None,
        )
        preset_label = (preset_row.name or preset_row.full_code) if preset_row is not None else ""
        return account_id, (preset_detail_id, preset_label), "", []
    required = dimensions_service.get_required_dimensions_for_account(account_id)
    covered = covered_dimension_type_ids or set()
    # طبقِ اصلاحِ ریشه‌ای: اگر معین بیش از یک بُعدِ الزامی داشته باشد (مثلاً
    # هم مرکزِ هزینه هم یک نوع‌بُعدِ اختصاصیِ دیگر)، قبلاً فقط اولین موردِ
    # فهرست (required[0]) بررسی می‌شد — اگر آن اولین مورد مرکزِ هزینه/پروژه
    # و پوشش‌یافته بود، کلِ معین «بدونِ تفصیلی» تلقی می‌شد و بُعدِ الزامیِ
    # دیگرش هیچ‌وقت دیده نمی‌شد. حالا کلِ فهرست پیموده می‌شود و اولین بُعدی
    # که مرکزِ هزینه/پروژه‌یِ پوشش‌یافته نباشد انتخاب می‌شود.
    chosen = next(
        (r for r in required if not (r.code in _HEADER_SHARED_DIMENSION_CODES and r.dimension_type_id in covered)),
        None,
    )
    if required and chosen is None:
        # همه‌ی بُعدهای الزامی مرکزِ هزینه/پروژه‌اند و هدر پوششان داده -> چیزی نمی‌پرسد
        return account_id, None, "", []
    if chosen is not None:
        label = (
            "تفصیلیِ اشخاص"
            if chosen.code == dimensions_service.PERSON_DIMENSION_CODE
            else dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(chosen.code, chosen.code)
        )
        return account_id, None, label, chosen.detail_accounts
    return account_id, None, "تفصیلی", dimensions_service.list_all_leaf_detail_accounts(company_id)


class _MethodDetailsDialog(QDialog):
    """جزئیاتِ مخصوصِ روشِ انتخاب‌شده‌یِ یک ردیف — نقد/بانک/تخفیف/کالابرگ:
    تفصیلیِ سطحِ آخرِ حسابِ معینِ نگاشته‌شده؛ چک (پرداخت): شماره/بانک/
    سررسید/طرف (+دسته‌چک)؛ خرجِ چک: کدام چکِ دریافتی؛ بن: سریال+مشخصات."""

    def __init__(
        self,
        direction: str,
        method: str,
        company_id: int,
        current: dict,
        parent=None,
        covered_dimension_type_ids: set[int] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"جزئیاتِ ردیفِ {_METHOD_LABELS.get(method, method)}")
        layout = QFormLayout(self)

        self.detail_combo: QComboBox | None = None
        self.preset_detail_id: int | None = None
        self.preset_detail_label: str = ""
        self.checkbook_combo: QComboBox | None = None
        self.check_no_field: QLineEdit | None = None
        self.check_bank_field: QLineEdit | None = None
        self.check_due_field: JalaliDateEdit | None = None
        self.check_party_field: QLineEdit | None = None
        self.received_check_combo: QComboBox | None = None
        self.voucher_serial_field: QLineEdit | None = None
        self.voucher_detail_field: QLineEdit | None = None

        if method in ("CASH", "BANK", "DISCOUNT", "GOODS_COUPON", "VOUCHER", "NETTING"):
            mapping_key = f"{direction}_{method}"
            _account_id, preset, label, options = _resolve_row_detail_source(
                company_id, mapping_key, covered_dimension_type_ids
            )
            if preset is not None:
                self.preset_detail_id, self.preset_detail_label = preset
            elif options:
                self.detail_combo = _make_searchable_combo(
                    [(o.detail_account_id, o.name or o.full_code or o.code) for o in options]
                )
                if current.get("detail_account_id") is not None:
                    index = self.detail_combo.findData(current["detail_account_id"])
                    if index >= 0:
                        self.detail_combo.setCurrentIndex(index)
                layout.addRow(label or "تفصیلی", self.detail_combo)
        if method == "VOUCHER":
            self.voucher_serial_field = QLineEdit(current.get("voucher_serial") or "")
            layout.addRow("سریالِ بن", self.voucher_serial_field)
            self.voucher_detail_field = QLineEdit(current.get("voucher_detail") or "")
            layout.addRow("مشخصاتِ بن", self.voucher_detail_field)
            if self.detail_combo is not None:
                self.detail_combo.lineEdit().returnPressed.connect(self.voucher_serial_field.setFocus)
            self.voucher_serial_field.returnPressed.connect(self.voucher_detail_field.setFocus)
            self.voucher_detail_field.returnPressed.connect(self.accept)
        elif self.detail_combo is not None:
            self.detail_combo.lineEdit().returnPressed.connect(self.accept)
        if method == "CHECK":
            # طبقِ درخواستِ صریح: این دیالوگ فقط برایِ سمتِ پرداخت (صدورِ
            # چکِ تازه از دسته‌چک) است — چکِ دریافتی از دیالوگِ چندچکیِ
            # _CheckEntryDialog وارد می‌شود.
            self.checkbook_combo = QComboBox()
            self.checkbook_combo.addItem("(بدونِ دسته‌چک — شماره‌یِ دستی)", None)
            for checkbook in treasury_service.list_checkbooks(company_id):
                if checkbook.is_active and checkbook.next_no <= checkbook.end_no:
                    self.checkbook_combo.addItem(
                        f"{checkbook.bank_account_label} "
                        f"({numerals.to_persian_digits(str(checkbook.next_no))}–{numerals.to_persian_digits(str(checkbook.end_no))})",
                        checkbook.checkbook_id,
                    )
            if current.get("checkbook_id") is not None:
                index = self.checkbook_combo.findData(current["checkbook_id"])
                if index >= 0:
                    self.checkbook_combo.setCurrentIndex(index)
            layout.addRow("دسته‌چک", self.checkbook_combo)

            bank_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.BANK_ACCOUNT_CODE)
            options = dimensions_service.list_leaf_detail_accounts(company_id, bank_type_id)
            self.detail_combo = QComboBox()
            for option in options:
                self.detail_combo.addItem(option.name or option.code, option.detail_account_id)
            if current.get("detail_account_id") is not None:
                index = self.detail_combo.findData(current["detail_account_id"])
                if index >= 0:
                    self.detail_combo.setCurrentIndex(index)
            layout.addRow("حسابِ بانکیِ صادرکننده", self.detail_combo)

            self.check_no_field = QLineEdit(current.get("check_no") or "")
            layout.addRow("شماره‌یِ چک", self.check_no_field)
            self.check_bank_field = QLineEdit(current.get("check_bank_name") or "")
            layout.addRow("بانکِ چک", self.check_bank_field)
            self.check_due_field = JalaliDateEdit("سررسید")
            self.check_due_field.setDate(current.get("check_due_date") or datetime.date.today())
            layout.addRow("سررسید", self.check_due_field)
            self.check_party_field = QLineEdit(current.get("check_party_name") or "")
            layout.addRow("نامِ طرف", self.check_party_field)
        elif method == "CHECK_DISBURSEMENT":
            self.received_check_combo = QComboBox()
            eligible_checks = treasury_service.list_received_checks(company_id, status_codes=["IN_HAND", "DEPOSITED"])
            for c in eligible_checks:
                label = f"چک {c.check_no} — {numerals.to_persian_digits(str(c.amount))} — سررسید {numerals.format_jalali_date(c.due_date)}"
                self.received_check_combo.addItem(label, (c.received_check_id, c.amount))
            if current.get("received_check_id") is not None:
                index = next(
                    (i for i in range(self.received_check_combo.count()) if self.received_check_combo.itemData(i)[0] == current["received_check_id"]),
                    -1,
                )
                if index >= 0:
                    self.received_check_combo.setCurrentIndex(index)
            layout.addRow("چکِ دریافتیِ خرج‌شونده", self.received_check_combo)

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

    def result_data(self) -> dict:
        data: dict = {}
        if self.preset_detail_id is not None:
            data["detail_account_id"] = self.preset_detail_id
            data["detail_account_label"] = self.preset_detail_label
        elif self.detail_combo is not None:
            data["detail_account_id"] = self.detail_combo.currentData()
            data["detail_account_label"] = self.detail_combo.currentText()
        if self.checkbook_combo is not None:
            data["checkbook_id"] = self.checkbook_combo.currentData()
        if self.check_no_field is not None:
            data["check_no"] = self.check_no_field.text().strip()
        if self.check_bank_field is not None:
            data["check_bank_name"] = self.check_bank_field.text().strip()
        if self.check_due_field is not None:
            data["check_due_date"] = self.check_due_field.date()
        if self.check_party_field is not None:
            data["check_party_name"] = self.check_party_field.text().strip()
        if self.received_check_combo is not None and self.received_check_combo.currentData() is not None:
            received_check_id, amount = self.received_check_combo.currentData()
            data["received_check_id"] = received_check_id
            data["check_amount"] = amount
        if self.voucher_serial_field is not None:
            data["voucher_serial"] = self.voucher_serial_field.text().strip()
        if self.voucher_detail_field is not None:
            data["voucher_detail"] = self.voucher_detail_field.text().strip()
        return data


_CHECK_ENTRY_COLUMNS = ["شماره‌یِ چک", "بانک", "مبلغ", "صاحبِ حساب"]


class _CheckEntryDialog(QDialog):
    """واردکردنِ چند چکِ دریافتی در یک ردیف — طبقِ درخواستِ صریح: سریال/
    شماره/شبا/بانک/شماره‌حساب/مبلغ/نامِ صاحبِ‌حساب/کدِملی/تلفن؛ با «تایید»
    جمعِ مبلغِ همه‌یِ چک‌ها به ردیف منتقل می‌شود."""

    def __init__(self, company_id: int, current_checks: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("چک‌هایِ دریافتی")
        self.setMinimumWidth(620)
        self._checks: list[dict] = list(current_checks or [])

        outer = QVBoxLayout(self)

        form = QGridLayout()
        form.setSpacing(6)
        self.serial_field = QLineEdit()
        self.no_field = QLineEdit()
        self.iban_field = QLineEdit()
        self.bank_combo = _EnterComboBox()
        self.bank_combo.addItem("—", None)
        for bank in treasury_service.list_banks(company_id, active_only=True):
            self.bank_combo.addItem(bank.name, bank.bank_id)
        self.account_no_field = QLineEdit()
        self.amount_field = _AmountField()
        self.due_field = JalaliDateEdit("سررسید")
        self.due_field.setDate(datetime.date.today())
        self.owner_field = QLineEdit()
        self.national_id_field = QLineEdit()
        self.phone_field = QLineEdit()

        # طبقِ درخواستِ صریح: با زدنِ Enter در هر فیلد، به فیلدِ بعدی برود؛
        # Enterِ فیلدِ آخر همان کاری را می‌کند که «+ افزودن» می‌کند.
        self.serial_field.returnPressed.connect(self.no_field.setFocus)
        self.no_field.returnPressed.connect(self.iban_field.setFocus)
        self.iban_field.returnPressed.connect(self.bank_combo.setFocus)
        self.bank_combo.enterPressed.connect(self.account_no_field.setFocus)
        self.account_no_field.returnPressed.connect(self.amount_field.setFocus)
        self.amount_field.returnPressed.connect(self.due_field.setFocus)
        self.due_field.returnPressed.connect(self.owner_field.setFocus)
        self.owner_field.returnPressed.connect(self.national_id_field.setFocus)
        self.national_id_field.returnPressed.connect(self.phone_field.setFocus)
        self.phone_field.returnPressed.connect(self._add_current)

        rows = [
            ("سریالِ چک", self.serial_field),
            ("شماره‌یِ چک", self.no_field),
            ("شماره‌یِ شبا", self.iban_field),
            ("بانک", self.bank_combo),
            ("شماره‌یِ حساب", self.account_no_field),
            ("مبلغ", self.amount_field),
            ("سررسید", self.due_field),
            ("نامِ صاحبِ حساب", self.owner_field),
            ("کدِ ملیِ صاحبِ حساب", self.national_id_field),
            ("تلفنِ صاحبِ حساب", self.phone_field),
        ]
        for row_index, (label, widget) in enumerate(rows):
            form.addWidget(QLabel(label), row_index // 2, (row_index % 2) * 2)
            form.addWidget(widget, row_index // 2, (row_index % 2) * 2 + 1)
        outer.addLayout(form)

        add_button = QPushButton("+ افزودنِ این چک به فهرست")
        add_button.setObjectName("flatButton")
        add_button.clicked.connect(self._add_current)
        outer.addWidget(add_button)

        self.table = QTableWidget(0, len(_CHECK_ENTRY_COLUMNS))
        self.table.setHorizontalHeaderLabels(_CHECK_ENTRY_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._remove_row)
        outer.addWidget(self.table)

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
        return {
            "check_serial": self.serial_field.text().strip() or None,
            "check_no": self.no_field.text().strip(),
            "iban": self.iban_field.text().strip() or None,
            "bank_id": self.bank_combo.currentData(),
            "check_bank_name": self.bank_combo.currentText() if self.bank_combo.currentData() is not None else None,
            "bank_account_no": self.account_no_field.text().strip() or None,
            "amount": amount,
            "due_date": self.due_field.date(),
            "party_name": self.owner_field.text().strip() or None,
            "national_id": self.national_id_field.text().strip() or None,
            "phone": self.phone_field.text().strip() or None,
        }

    def _append_table_row(self, entry: dict) -> None:
        row_index = self.table.rowCount()
        self.table.insertRow(row_index)
        self.table.setItem(row_index, 0, QTableWidgetItem(entry.get("check_no") or ""))
        self.table.setItem(row_index, 1, QTableWidgetItem(entry.get("check_bank_name") or ""))
        self.table.setItem(row_index, 2, QTableWidgetItem(numerals.to_persian_digits(str(entry["amount"]))))
        self.table.setItem(row_index, 3, QTableWidgetItem(entry.get("party_name") or ""))

    def _clear_fields(self) -> None:
        self.serial_field.clear()
        self.no_field.clear()
        self.iban_field.clear()
        self.bank_combo.setCurrentIndex(0)
        self.account_no_field.clear()
        self.amount_field.setValue(0)
        self.owner_field.clear()
        self.national_id_field.clear()
        self.phone_field.clear()

    def _add_current(self) -> None:
        entry = self._current_entry()
        if entry is None:
            return
        self._checks.append(entry)
        self._append_table_row(entry)
        self._clear_fields()
        self._update_total()
        self.serial_field.setFocus()

    def _remove_row(self, row: int, _column: int) -> None:
        self.table.removeRow(row)
        self._checks.pop(row)
        self._update_total()

    def _update_total(self) -> None:
        total = sum((c["amount"] for c in self._checks), decimal.Decimal(0))
        self.total_label.setText(f"جمعِ مبلغِ چک‌ها: {numerals.to_persian_digits(str(total))} ({numerals.to_persian_digits(str(len(self._checks)))} چک)")

    def _on_accept(self) -> None:
        # اگر چکی در فیلدها آماده ولی هنوز به فهرست افزوده نشده، پیش از
        # تایید خودکار اضافه می‌شود — تا کاربر مجبور نباشد حتماً «+ افزودن»
        # را جداگانه بزند.
        entry = self._current_entry()
        if entry is not None:
            self._checks.append(entry)
            self._append_table_row(entry)
            self._clear_fields()
            self._update_total()
        if not self._checks:
            QMessageBox.warning(self, "چکِ دریافتی", "حداقل یک چک وارد کنید.")
            return
        self.accept()

    def result_checks(self) -> list[dict]:
        return list(self._checks)


class _MethodRow:
    def __init__(self, screen: "TreasuryVoucherScreen") -> None:
        self._screen = screen
        self.details: dict = {}

        self.method_combo = _EnterComboBox()
        method_codes = _RECEIPT_METHOD_CODES if screen.direction == "RECEIPT" else _PAYMENT_METHOD_CODES
        for code in method_codes:
            self.method_combo.addItem(_METHOD_LABELS[code], code)
        self.method_combo.enterPressed.connect(self._on_method_return)
        self.method_combo.currentIndexChanged.connect(lambda _i: self._regenerate_description())

        self.amount_field = _AmountField()
        self.amount_field.setDecimals(screen.currency_decimal_places)
        self.amount_field.returnPressed.connect(lambda: self.description_field.setFocus())
        self.amount_field.valueChanged.connect(lambda _v: self._regenerate_description())
        self.amount_field.valueChanged.connect(lambda _v: screen._update_rows_summary())

        self.description_field = QLineEdit()
        self.description_field.returnPressed.connect(lambda: screen._focus_next_row_after(self))

        self.details_button = QPushButton("جزئیات…")
        self.details_button.setObjectName("flatButton")
        self.details_button.clicked.connect(self._open_details)

        self.remove_button = QPushButton("✕")
        self.remove_button.setObjectName("dangerButton")
        self.remove_button.clicked.connect(lambda: screen._remove_row(self))

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
        if method == "CHECK" and self._screen.direction == "RECEIPT":
            dialog = _CheckEntryDialog(self._screen.company_id, self.details.get("checks") or [], self._screen)
            if dialog.exec() == QDialog.Accepted:
                checks = dialog.result_checks()
                self.details = {"checks": checks}
                total = sum((c["amount"] for c in checks), decimal.Decimal(0))
                self.amount_field.setValue(float(total))
                self._regenerate_description()
                self.description_field.setFocus()
            return
        if method in _MAPPING_ONLY_DETAIL_METHODS:
            # طبقِ درخواستِ صریح: اگر تفصیلیِ این روش از پیش در تنظیمات
            # تخصیص یافته، دیگر دیالوگ باز نمی‌شود (خودکار اعمال می‌شود)؛
            # اگر نه پیش‌تخصیص هست نه هیچ گزینه‌ای، دیالوگِ خالی هم باز نمی‌شود.
            mapping_key = f"{self._screen.direction}_{method}"
            _account_id, preset, _label, options = _resolve_row_detail_source(
                self._screen.company_id, mapping_key, set(self._screen._detail_combos.keys())
            )
            if preset is not None:
                self.details = {"detail_account_id": preset[0], "detail_account_label": preset[1]}
                self._regenerate_description()
                self.amount_field.setFocus()
                return
            if not options:
                self._regenerate_description()
                self.amount_field.setFocus()
                return
        dialog = _MethodDetailsDialog(
            self._screen.direction,
            method,
            self._screen.company_id,
            self.details,
            self._screen,
            covered_dimension_type_ids=set(self._screen._detail_combos.keys()),
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
            "مبلغ": numerals.to_persian_digits(f"{amount:,.0f}") if amount else "",
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
        if method in ("CASH", "BANK", "DISCOUNT", "GOODS_COUPON", "VOUCHER", "NETTING"):
            kwargs["detail_account_id"] = self.details.get("detail_account_id")
        elif method == "CHECK":
            if "checks" in self.details:
                kwargs["checks"] = self.details["checks"]
            else:
                kwargs.update(
                    detail_account_id=self.details.get("detail_account_id"),
                    check_no=self.details.get("check_no") or "",
                    check_bank_name=self.details.get("check_bank_name"),
                    check_due_date=self.details.get("check_due_date"),
                    check_party_name=self.details.get("check_party_name"),
                    checkbook_id=self.details.get("checkbook_id"),
                )
        elif method == "CHECK_DISBURSEMENT":
            kwargs["received_check_id"] = self.details.get("received_check_id")
        return treasury_service.MethodLine(**kwargs)


class TreasuryVoucherScreen(FieldHelpMixin, QWidget):
    def __init__(self, direction: str) -> None:
        super().__init__()
        self.direction = direction  # "RECEIPT" یا "PAYMENT"
        self.company_id: int | None = None
        self.currency_decimal_places = 0
        self.account_options: list[tuple[int, str]] = []
        self._detail_combos: dict[int, QComboBox] = {}
        self._method_rows: list[_MethodRow] = []
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(5)

        header_card = QWidget()
        header_card.setObjectName("card")
        header_layout = QGridLayout(header_card)
        header_layout.setContentsMargins(10, 6, 10, 4)
        header_layout.setSpacing(3)

        self.title_label = QLabel(f"سندِ {noun}")
        self.title_label.setObjectName("pageTitle")
        header_layout.addWidget(self.title_label, 0, 0, 1, 5)

        header_layout.addWidget(QLabel("طرفِ حساب (تفصیلی)"), 1, 0)
        self.account_combo = _make_searchable_combo([])
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        header_layout.addWidget(self.account_combo, 1, 1)

        # طبقِ درخواستِ صریح: مرکزِ هزینه/پروژه (اگر رویِ حسابِ طرف‌حساب
        # الزامی باشند) به‌جایِ یک ردیفِ جداگانه‌یِ زیرِ هدر، همین‌جا جلویِ
        # خودِ تفصیلیِ طرفِ‌حساب می‌آیند — افقی و جمع‌وجور.
        self.detail_container = QHBoxLayout()
        self.detail_container.setContentsMargins(0, 0, 0, 0)
        self.detail_container.setSpacing(4)
        header_layout.addLayout(self.detail_container, 1, 2)

        header_layout.addWidget(QLabel("تاریخ"), 1, 3)
        self.date_field = JalaliDateEdit("تاریخِ سند")
        self.date_field.setMaximumWidth(120)
        header_layout.addWidget(self.date_field, 1, 4)

        header_layout.addWidget(QLabel("شرح"), 2, 0)
        self.description_field = QLineEdit()
        header_layout.addWidget(self.description_field, 2, 1, 1, 2 if direction == "RECEIPT" else 4)

        self.total_amount_field: _AmountField | None = None
        self.rows_summary_label: QLabel | None = None
        if direction == "RECEIPT":
            header_layout.addWidget(QLabel("جمعِ مبلغِ دریافتی"), 2, 3)
            self.total_amount_field = _AmountField()
            self.total_amount_field.setMaximumWidth(160)
            self.total_amount_field.valueChanged.connect(lambda _v: self._update_rows_summary())
            header_layout.addWidget(self.total_amount_field, 2, 4)

            # طبقِ درخواستِ صریح: جمعِ زنده‌یِ ردیف‌ها + اختلافش با جمعِ
            # دریافتیِ هدر، همین‌جا نمایش داده شود.
            self.rows_summary_label = QLabel("")
            self.rows_summary_label.setObjectName("sectionHint")
            header_layout.addWidget(self.rows_summary_label, 3, 0, 1, 5)

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
        if self.total_amount_field is not None:
            self.description_field.returnPressed.connect(lambda: self.total_amount_field.setFocus())
            self.total_amount_field.returnPressed.connect(self._focus_first_row_method)
        else:
            self.description_field.returnPressed.connect(self._focus_first_row_method)

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
        add_row_button = QPushButton("+ ردیفِ روش")
        add_row_button.setObjectName("flatButton")
        add_row_button.clicked.connect(self._add_row)
        rows_header.addWidget(add_row_button)
        table_card_layout.addLayout(rows_header)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["روش", "مبلغ", "شرح", "جزئیات", ""])
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
        self.table.setColumnWidth(4, 36)
        table_card_layout.addWidget(self.table, stretch=1)

        layout.addWidget(table_card, stretch=1)

        footer = QHBoxLayout()
        save_button = QPushButton(f"ثبتِ سندِ {noun}")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save)
        footer.addWidget(save_button)
        footer.addStretch(1)
        layout.addLayout(footer)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

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
        if self.total_amount_field is not None:
            help_fields.insert(
                1,
                (
                    self.total_amount_field,
                    "جمعِ مبلغی که دریافت شده — جمعِ ردیف‌هایِ پایین باید دقیقاً با همین مبلغ برابر باشد تا سند ثبت شود.",
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

        base_currency_id = session.current_company.base_currency_id if session.current_company else None
        currency = next((c for c in currencies_service.list_all_currencies() if c.currency_id == base_currency_id), None)
        self.currency_decimal_places = currency.decimal_places if currency else 0
        if self.total_amount_field is not None:
            self.total_amount_field.setDecimals(self.currency_decimal_places)

        self._description_templates = {
            t.template_key: t.template_text for t in treasury_service.list_description_templates(self.company_id, self.direction)
        }

        self._reset_form()

    def _counterparty_label(self) -> str:
        detail_account_id = self.account_combo.currentData()
        return next((label for oid, label in self.account_options if oid == detail_account_id), "")

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
                    options.append((d.detail_account_id, d.name or d.full_code or d.code))
        for dimension_type_id, account_id in dim_mapping_by_type.items():
            for d in dimensions_service.list_leaf_detail_accounts(self.company_id, dimension_type_id):
                self._counterparty_index[d.detail_account_id] = (account_id, dimension_type_id)
                options.append((d.detail_account_id, d.name or d.full_code or d.code))
        return options

    def _on_account_changed(self, _index: int) -> None:
        while self.detail_container.count():
            child = self.detail_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._detail_combos = {}

        if self.company_id is None:
            return

        detail_account_id = self.account_combo.currentData()
        if detail_account_id is None or detail_account_id not in self._counterparty_index:
            return
        account_id, resolved_dimension_type_id = self._counterparty_index[detail_account_id]
        skip_dimension_type_id = resolved_dimension_type_id

        # طبقِ درخواستِ صریح: این کمبوها (مرکزِ هزینه/پروژه) افقی و جلویِ
        # خودِ طرفِ‌حساب می‌آیند — نه یک ردیفِ جداگانه؛ برایِ همین به‌جایِ
        # ویجت‌بندیِ عمودیِ قبلی، مستقیم به‌ترتیب در detail_containerِ افقی
        # اضافه می‌شوند و زنجیره‌یِ Enter از رویِ همین ترتیب ساخته می‌شود.
        combos: list[QComboBox] = []
        for required in dimensions_service.get_required_dimensions_for_account(account_id):
            if required.dimension_type_id == skip_dimension_type_id:
                continue  # این بُعد از طریقِ تفصیلیِ طرفِ‌حسابِ انتخاب‌شده حل شده
            label = "تفصیلیِ اشخاص" if required.code == dimensions_service.PERSON_DIMENSION_CODE else dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(required.code, required.code)
            self.detail_container.addWidget(QLabel(label))
            combo = _make_searchable_combo([(d.detail_account_id, d.name or d.full_code or d.code) for d in required.detail_accounts])
            combo.setMaximumWidth(160)
            self.detail_container.addWidget(combo)
            self._detail_combos[required.dimension_type_id] = combo
            combos.append(combo)

        # زنجیره‌یِ Enter از میانِ همین کمبوهایِ پویا تا تاریخ.
        for combo, next_combo in zip(combos, combos[1:]):
            combo.lineEdit().returnPressed.connect(next_combo.setFocus)
        if combos:
            combos[-1].lineEdit().returnPressed.connect(self.date_field.setFocus)

        # طبقِ درخواستِ صریح: طرفِ‌حساب در متنِ خودکارِ شرحِ همه‌یِ ردیف‌ها
        # به‌کار می‌رود — با تغییرش، شرحِ همه‌یِ ردیف‌ها هم به‌روز شود.
        for row in self._method_rows:
            row._regenerate_description()

    def _on_account_return(self) -> None:
        if self._detail_combos:
            first_combo = next(iter(self._detail_combos.values()))
            first_combo.setFocus()
            first_combo.lineEdit().selectAll()
        else:
            self.date_field.setFocus()

    def _add_row(self) -> _MethodRow:
        row = _MethodRow(self)
        row_index = self.table.rowCount()
        self.table.insertRow(row_index)
        self.table.setCellWidget(row_index, 0, row.method_combo)
        self.table.setCellWidget(row_index, 1, row.amount_field)
        self.table.setCellWidget(row_index, 2, row.description_field)
        self.table.setCellWidget(row_index, 3, row.details_button)
        self.table.setCellWidget(row_index, 4, row.remove_button)
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

    def _update_rows_summary(self) -> None:
        """طبقِ درخواستِ صریح: جمعِ زنده‌یِ ردیف‌ها و اختلافش با جمعِ مبلغِ
        دریافتیِ هدر، همان‌جایِ هدر نمایش داده شود."""
        if self.rows_summary_label is None or self.total_amount_field is None:
            return
        rows_total = sum(
            (decimal.Decimal(str(row.amount_field.value())) for row in self._method_rows), decimal.Decimal(0)
        )
        header_total = decimal.Decimal(str(self.total_amount_field.value()))
        diff = header_total - rows_total
        theme.set_status_label(
            self.rows_summary_label,
            f"جمعِ ردیف‌ها: {numerals.to_persian_digits(str(rows_total))}    —    "
            f"اختلاف با جمعِ دریافتی: {numerals.to_persian_digits(str(diff))}",
            ok=(diff == 0),
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
        self._add_row()
        self.date_field.setDate(datetime.date.today())
        self.description_field.clear()
        if self.total_amount_field is not None:
            self.total_amount_field.setValue(0)
        self.account_combo.setCurrentIndex(0)
        self.status_label.setText("")
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
                if combo.currentData() is not None
            }
        )
        method_lines = [ln for row in self._method_rows if (ln := row.to_method_line()) is not None]
        if not method_lines:
            theme.set_status_label(self.status_label, "حداقل یک ردیفِ روش (با مبلغِ مثبت) لازم است.", ok=False)
            return

        if self.total_amount_field is not None:
            header_total = decimal.Decimal(str(self.total_amount_field.value()))
            if header_total <= 0:
                theme.set_status_label(self.status_label, "جمعِ مبلغِ دریافتی را در هدر وارد کنید.", ok=False)
                return
            rows_total = sum((ln.amount for ln in method_lines), decimal.Decimal(0))
            if rows_total != header_total:
                theme.set_status_label(
                    self.status_label,
                    f"جمعِ ردیف‌ها ({numerals.to_persian_digits(str(rows_total))}) با مبلغِ دریافتیِ هدر "
                    f"({numerals.to_persian_digits(str(header_total))}) برابر نیست.",
                    ok=False,
                )
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
            )
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return

        self._reset_form()
        theme.set_status_label(
            self.status_label,
            f"سند با شماره‌ی موقتِ {numerals.to_persian_digits(str(result.temporary_no))} ثبت شد.",
            ok=True,
        )
