"""مدیریتِ چک‌هایِ دریافتی و پرداختی — طبقِ الگویِ نمونه‌یِ ارائه‌شده: فهرستی
از مراحلِ چرخه‌یِ چک (رادیو)، جدولی چندانتخابی (چک‌باکس) از چک‌هایِ
واجدِ شرایطِ همان مرحله، و یک دکمه‌یِ تاییدِ نهایی که همه‌یِ چک‌هایِ
تیک‌خورده را یک‌جا پردازش می‌کند (services/treasury.py: توابعِ bulk)."""

from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import treasury as treasury_service
from peecha.ui.screens.journal_entry import _make_searchable_combo
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit, build_action_footer

_RECEIVED_STATUS_LABELS = {
    "IN_HAND": "نزدِ صندوق",
    "DEPOSITED": "واگذارشده به بانک",
    "CLEARED": "وصول‌شده",
    "BOUNCED": "برگشت‌خورده",
    "ENDORSED": "خرج‌شده نزدِ شخصِ ثالث",
}
_ISSUED_STATUS_LABELS = {
    "ISSUED": "صادر/نزدِ گیرنده",
    "CLEARED": "وصول‌شده",
    "BOUNCED": "برگشت‌خورده",
    "VOIDED": "ابطال‌شده",
}


@dataclasses.dataclass
class _StageConfig:
    key: str
    label: str
    eligible_status_codes: tuple[str, ...]
    target_dimension_code: str | None  # CASH_BOX_CODE / BANK_ACCOUNT_CODE / None
    target_label: str = ""
    confirm_message: str = ""


_RECEIVED_STAGES: list[_StageConfig] = [
    _StageConfig(
        "TRANSFER", "چک‌هایِ دریافتی جهتِ انتقال بینِ صندوق‌ها", ("IN_HAND",),
        dimensions_service.CASH_BOX_CODE, "صندوقِ مقصد",
    ),
    _StageConfig(
        "CASH_COLLECT", "چک‌هایِ نزدِ صندوق جهتِ وصولِ نقدی", ("IN_HAND",),
        dimensions_service.CASH_BOX_CODE, "صندوقِ نقدیِ مقصد",
    ),
    _StageConfig(
        "BANK_DEPOSIT", "چک‌هایِ نزدِ صندوق جهتِ واگذاری به بانک", ("IN_HAND",),
        dimensions_service.BANK_ACCOUNT_CODE, "بانکِ مقصد",
    ),
    _StageConfig(
        "BANK_CLEAR", "چک‌هایِ دریافتیِ نزدِ بانک جهتِ اعلامِ وصول", ("DEPOSITED",),
        None,
    ),
    _StageConfig(
        "BANK_RETURN", "چک‌هایِ دریافتیِ نزدِ بانک جهتِ برگشت به صندوق", ("DEPOSITED",),
        dimensions_service.CASH_BOX_CODE, "صندوقِ مقصد",
    ),
    _StageConfig(
        "CUSTOMER_RETURN", "چک‌هایِ نزدِ صندوق جهتِ برگشت به طرفِ‌حساب", ("IN_HAND",),
        None, confirm_message="این چک(ها) برگشت خورده‌اند؟ بدهیِ طرفِ‌حساب دوباره ثبت می‌شود.",
    ),
    _StageConfig(
        "ENDORSED_RETURN", "چک‌هایِ خرجی جهتِ برگشت به صندوق", ("ENDORSED",),
        dimensions_service.CASH_BOX_CODE, "صندوقِ مقصد",
    ),
]

_ISSUED_STAGES: list[_StageConfig] = [
    _StageConfig(
        "BANK_CLEAR", "چک‌هایِ پرداختی جهتِ وصول از بانک", ("ISSUED",),
        None,
    ),
    _StageConfig(
        "RETURN_TO_FUND", "چک‌هایِ پرداختیِ وصول‌نشده جهتِ برگشت به صندوق", ("ISSUED", "BOUNCED"),
        None, confirm_message="این چک(ها) به صندوق برگردانده شوند؟ بدهیِ ما به طرفِ‌حساب دوباره ثبت می‌شود.",
    ),
]


class _CheckHistoryDialog(QDialog):
    """گزارشِ کاملِ چرخه‌یِ عمرِ یک چک — طبقِ درخواستِ صریح: «چک‌ها باید در
    هر مرحله ثبت بشه و بتوان گزارش گرفت» — برایِ هر رویداد، شماره‌یِ سندِ
    حسابداریِ همان مرحله نمایش داده می‌شود. طبقِ درخواستِ صریحِ بعدی («سندِ
    مرحله‌یِ آخر حذف بشه تا چک برگرده به حالتِ اول»)، اگر آخرین رویداد هنوز
    قابلِ‌برگشت باشد (سندش هنوز موقت است)، دکمه‌یِ «حذفِ آخرین سندِ مرحله»
    هم نمایش داده می‌شود."""

    _COLUMNS = ["مرحله", "تاریخ", "از وضعیت", "به وضعیت", "شماره‌یِ سند"]

    def __init__(self, check_kind: str, check_id: int, check_no: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"تاریخچه‌یِ چکِ شماره‌یِ {numerals.to_persian_digits(check_no)}")
        self.resize(720, 460)
        self._check_kind = check_kind
        self._check_id = check_id
        self.undo_performed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel(f"تاریخچه‌یِ چکِ شماره‌یِ {numerals.to_persian_digits(check_no)}")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        table = QTableWidget(0, len(self._COLUMNS))
        table.setHorizontalHeaderLabels(self._COLUMNS)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(table, stretch=1)

        company_id = session.current_company.company_id if session.current_company else None
        events = (
            treasury_service.get_check_stage_history(company_id, check_kind, check_id)
            if company_id is not None
            else []
        )
        table.setRowCount(len(events))
        status_labels = _RECEIVED_STATUS_LABELS if check_kind == "RECEIVED" else _ISSUED_STATUS_LABELS
        for row_index, event in enumerate(events):
            if event.journal_entry_id is None:
                doc_label = "—"
            elif event.journal_permanent_no is not None:
                doc_label = f"دائم: {numerals.to_persian_digits(str(event.journal_permanent_no))}"
            else:
                doc_label = f"موقت: {numerals.to_persian_digits(str(event.journal_temporary_no))}"
            values = [
                event.event_label,
                numerals.format_jalali_date(event.event_date),
                status_labels.get(event.from_status_code, event.from_status_code or "—"),
                status_labels.get(event.to_status_code, event.to_status_code),
                doc_label,
            ]
            for col_index, value in enumerate(values):
                table.setItem(row_index, col_index, QTableWidgetItem(value))
        if not events:
            layout.addWidget(QLabel("هیچ رویدادی برایِ این چک ثبت نشده است."))

        last_event = events[-1] if events else None
        can_undo = (
            last_event is not None
            and last_event.event_code != "REGISTERED"
            and (last_event.journal_entry_id is None or last_event.journal_permanent_no is None)
        )
        if can_undo:
            hint = QLabel(
                "با «حذفِ آخرین سندِ مرحله»، سندِ حسابداریِ همین مرحله (اگر هنوز موقت باشد) حذف می‌شود "
                "و چک دقیقاً به وضعیت/محلِ پیش‌از‌آن برمی‌گردد."
            )
            hint.setWordWrap(True)
            hint.setObjectName("sectionHint")
            layout.addWidget(hint)
            undo_button = QPushButton("↩️")
            undo_button.setObjectName("dangerIconButton")
            undo_button.setFixedWidth(44)
            undo_button.setToolTip("حذفِ آخرین سندِ مرحله")
            undo_button.clicked.connect(self._undo_last_stage)
            layout.addWidget(undo_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _undo_last_stage(self) -> None:
        confirm = QMessageBox.question(
            self, "حذفِ آخرین سندِ مرحله",
            "سندِ حسابداریِ آخرین مرحله حذف و چک به وضعیتِ پیش‌از‌آن برمی‌گردد. ادامه می‌دهید؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        company_id = session.current_company.company_id if session.current_company else None
        if company_id is None or session.current_user is None:
            return
        try:
            treasury_service.undo_last_check_stage(self._check_kind, self._check_id, company_id, session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.undo_performed = True
        self.accept()


class ReceivedChecksScreen(FieldHelpMixin, QWidget):
    _COLUMNS = ["شماره‌یِ چک", "بانکِ صادرکننده", "نامِ صادرکننده", "مبلغ", "سررسید", "تاریخِ دریافت", "محلِ فعلی"]
    _DATE_BASIS_OPTIONS = [("due_date", "سررسید"), ("received_date", "تاریخِ دریافت")]

    def __init__(self) -> None:
        super().__init__()
        self._checks: list[treasury_service.ReceivedCheckRow] = []
        self._filtered_checks: list[treasury_service.ReceivedCheckRow] = []
        self._stage: _StageConfig = _RECEIVED_STAGES[0]

        # طبقِ آیتم‌هایِ ۱-۳: محتوایِ متغیرِ فرم (مراحل/فیلتر/جدول) داخلِ یک
        # QScrollArea + کارت؛ دکمه‌هایِ عملیات در نوارِ ثابتِ زیرِ اسکرول —
        # هم‌الگو با chart_of_accounts.py. باگِ «دکمه‌ها زیرِ تسک‌بار
        # می‌روند» دقیقاً از نبودِ همین اسکرول می‌آمد: فهرستِ عمودیِ ۷تاییِ
        # مراحل آن‌قدر جا می‌گرفت که کلِ فرم از ارتفاعِ صفحه بلندتر
        # می‌شد و پنجره را با خودش بزرگ‌تر از صفحه می‌کرد.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(10)

        title = QLabel("چک‌هایِ دریافتی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # طبقِ آیتمِ ۱: به‌جایِ فهرستِ عمودیِ ۷ردیفی (که خیلی جا می‌گرفت)،
        # دو ستون و فاصله‌یِ کمتر.
        self._stage_group = QButtonGroup(self)
        stage_grid = QGridLayout()
        stage_grid.setHorizontalSpacing(24)
        stage_grid.setVerticalSpacing(1)
        half = (len(_RECEIVED_STAGES) + 1) // 2
        for index, stage in enumerate(_RECEIVED_STAGES):
            radio = QRadioButton(stage.label)
            radio.setChecked(index == 0)
            radio.toggled.connect(lambda checked, s=stage: self._on_stage_selected(s) if checked else None)
            self._stage_group.addButton(radio)
            stage_grid.addWidget(radio, index % half, index // half)
        layout.addLayout(stage_grid)

        # طبقِ آیتمِ ۲: فیلترِ بازه‌یِ تاریخ (بر اساسِ سررسید یا تاریخِ
        # دریافت، به‌انتخابِ کاربر) + جست‌وجویِ طرفِ‌حساب (نامِ صادرکننده).
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("مبنایِ فیلترِ تاریخ:"))
        self.date_basis_combo = QComboBox()
        for value, label in self._DATE_BASIS_OPTIONS:
            self.date_basis_combo.addItem(label, value)
        self.date_basis_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.date_basis_combo)
        self.date_filter_enabled = QCheckBox("فعال")
        self.date_filter_enabled.toggled.connect(self._apply_filters)
        filter_row.addWidget(self.date_filter_enabled)
        filter_row.addWidget(QLabel("از"))
        self.date_from_field = JalaliDateEdit()
        self.date_from_field.editingFinished.connect(self._apply_filters)
        filter_row.addWidget(self.date_from_field)
        filter_row.addWidget(QLabel("تا"))
        self.date_to_field = JalaliDateEdit()
        self.date_to_field.editingFinished.connect(self._apply_filters)
        filter_row.addWidget(self.date_to_field)
        filter_row.addWidget(QLabel("طرفِ‌حساب:"))
        self.counterparty_filter_field = QLineEdit()
        self.counterparty_filter_field.setPlaceholderText("جست‌وجو در نامِ صادرکننده…")
        self.counterparty_filter_field.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.counterparty_filter_field, stretch=1)
        layout.addLayout(filter_row)

        # طبقِ آیتمِ ۶: «راسِ روز» — تاریخِ میانگینِ وزنیِ چک‌هایِ تیک‌خورده
        # (اگر چیزی تیک نخورده باشد، رویِ همه‌یِ چک‌هایِ فیلترشده‌یِ فعلی).
        self.ras_label = QLabel("")
        self.ras_label.setObjectName("raasLabel")
        layout.addWidget(self.ras_label)

        self.table = QTableWidget(0, len(self._COLUMNS) + 1)
        self.table.setHorizontalHeaderLabels([""] + self._COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 32)
        self.table.setMinimumHeight(240)
        self.table.cellDoubleClicked.connect(lambda *_: self._show_history())
        self.table.itemChanged.connect(lambda _item: self._update_ras_label())
        layout.addWidget(self.table, stretch=1)

        scroll.setWidget(panel)

        wrapper = QWidget()
        wrapper.setObjectName("card")
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(0)
        wrapper_layout.addWidget(scroll, stretch=1)

        footer = QWidget()
        footer.setObjectName("formFooter")
        # طبقِ قانونِ ثابتِ چیدمان («همه‌یِ آیکن‌ها کنارِ هم، سمتِ چپِ
        # پایینِ فرم»): QBoxLayout.setDirection به‌تنهایی اثری ندارد — Qt
        # جهتِ نمایشِ آن را از layoutDirection() خودِ ویجتِ فوتر می‌گیرد،
        # نه از Direction enum؛ پس باید صریحاً LTR شود. دکمه‌ها قبل از
        # target_label/target_combo اضافه می‌شوند تا همیشه چپ بنشینند —
        # ایندکسِ پویایِ target_combo (پایین‌تر، برایِ جایگزینی‌اش) با
        # ترتیبِ افزودن کاری ندارد، پس این تغییر امن است.
        footer.setLayoutDirection(Qt.LeftToRight)
        self._action_row = QHBoxLayout(footer)
        self._action_row.setContentsMargins(18, 12, 18, 14)
        self._action_row.setSpacing(8)
        self.history_button = QPushButton("🕒")
        self.history_button.setObjectName("iconButton")
        self.history_button.setFixedWidth(44)
        self.history_button.setToolTip("تاریخچه")
        self.history_button.clicked.connect(self._show_history)
        self._action_row.addWidget(self.history_button)
        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذفِ چک")
        self.delete_button.clicked.connect(self._delete_check)
        self._action_row.addWidget(self.delete_button)
        self.confirm_button = QPushButton("✅")
        self.confirm_button.setObjectName("iconButton")
        self.confirm_button.setFixedWidth(44)
        self.confirm_button.setToolTip("تاییدِ عملیات")
        self.confirm_button.clicked.connect(self._apply_stage)
        self._action_row.addWidget(self.confirm_button)
        self._action_row.addStretch(1)
        self.target_label = QLabel("")
        self.target_combo = QComboBox()
        self._action_row.addWidget(self.target_label)
        self._action_row.addWidget(self.target_combo)
        wrapper_layout.addWidget(footer)

        outer.addWidget(wrapper, stretch=1)

        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

        self.set_field_help([
            (
                self.table,
                "بالا مرحله‌یِ موردِنظر را انتخاب کنید — فهرست به چک‌هایِ واجدِ شرایطِ همان مرحله به‌روز می‌شود؛ "
                "چک(ها) را تیک بزنید و «تاییدِ عملیات» را بزنید تا همه‌یِ چک‌هایِ تیک‌خورده یک‌جا پردازش شوند.",
            ),
        ])

        self._on_stage_selected(self._stage)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _on_stage_selected(self, stage: _StageConfig) -> None:
        self._stage = stage
        # طبقِ الگویِ موجود: کمبویِ مقصد باید جست‌وجوپذیر باشد (هم‌الگو با
        # بقیه‌ی فرمِ خزانه‌داری) — چون _make_searchable_combo هربار یک
        # ویجتِ تازه می‌سازد، جایگزینیِ آن در چیدمان لازم است.
        old_index = self._action_row.indexOf(self.target_combo)
        self._action_row.removeWidget(self.target_combo)
        self.target_combo.deleteLater()
        if stage.target_dimension_code is None:
            options: list[tuple[int, str]] = []
        else:
            company_id = self._company_id()
            options = []
            if company_id is not None:
                type_id = dimensions_service.get_specialized_dimension_type_id(company_id, stage.target_dimension_code)
                options = [
                    (o.detail_account_id, o.name or o.code)
                    for o in dimensions_service.list_leaf_detail_accounts(company_id, type_id)
                ]
        self.target_combo = _make_searchable_combo(options)
        self._action_row.insertWidget(old_index, self.target_combo)
        has_target = stage.target_dimension_code is not None
        self.target_label.setVisible(has_target)
        self.target_combo.setVisible(has_target)
        self.target_label.setText(stage.target_label)
        self.refresh()

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self._checks = []
            self.table.setRowCount(0)
            return
        self._checks = treasury_service.list_received_checks(company_id, status_codes=list(self._stage.eligible_status_codes))
        self._apply_filters()

    def _apply_filters(self) -> None:
        """طبقِ آیتمِ ۲: فیلترِ بازه‌یِ تاریخ (بر مبنایِ سررسید یا تاریخِ
        دریافت) + جست‌وجویِ طرفِ‌حساب — رویِ همان self._checksِ از قبل
        واکشی‌شده، بدونِ کوئریِ تازه."""
        query = self.counterparty_filter_field.text().strip().lower()
        use_date_filter = self.date_filter_enabled.isChecked()
        basis = self.date_basis_combo.currentData() or "due_date"
        date_from = self.date_from_field.date() if use_date_filter else None
        date_to = self.date_to_field.date() if use_date_filter else None

        self._filtered_checks = []
        for c in self._checks:
            if query and query not in (c.drawer_name or "").lower():
                continue
            if use_date_filter:
                check_date = c.due_date if basis == "due_date" else c.received_date
                if date_from is not None and check_date < date_from:
                    continue
                if date_to is not None and check_date > date_to:
                    continue
            self._filtered_checks.append(c)

        self.table.setRowCount(len(self._filtered_checks))
        for row_index, c in enumerate(self._filtered_checks):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Unchecked)
            check_item.setData(Qt.UserRole, c.received_check_id)
            self.table.setItem(row_index, 0, check_item)
            values = [
                c.check_no,
                c.drawee_bank_name or "—",
                c.drawer_name or "—",
                numerals.format_money(c.amount, 0, None),
                numerals.format_jalali_date(c.due_date),
                numerals.format_jalali_date(c.received_date),
                c.current_location_label or "—",
            ]
            for col_index, value in enumerate(values, start=1):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
        self._update_ras_label()

    def _update_ras_label(self) -> None:
        """طبقِ آیتمِ ۶: «راسِ روز» — رویِ چک‌هایِ تیک‌خورده (اگر چیزی
        تیک نخورده، رویِ همه‌ی چک‌هایِ فیلترشده‌یِ فعلی)."""
        checked_ids = set(self._checked_check_ids())
        subset = [c for c in self._filtered_checks if c.received_check_id in checked_ids] if checked_ids else self._filtered_checks
        if not subset:
            self.ras_label.setText("")
            return
        ras_date, total = treasury_service.compute_check_ras([(c.amount, c.due_date) for c in subset])
        scope_word = "چک‌هایِ تیک‌خورده" if checked_ids else "همه‌ی چک‌هایِ نمایش‌داده‌شده"
        self.ras_label.setText(
            f"راسِ روز ({scope_word}): {numerals.format_jalali_date(ras_date)}    —    "
            f"جمعِ مبلغ: {numerals.format_money(total, 0, None)}"
        )

    def _checked_check_ids(self) -> list[int]:
        ids = []
        for row_index in range(self.table.rowCount()):
            item = self.table.item(row_index, 0)
            if item is not None and item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def _apply_stage(self) -> None:
        company_id = self._company_id()
        check_ids = self._checked_check_ids()
        if company_id is None or session.current_user is None or not check_ids:
            return
        stage = self._stage
        target_detail_id = self.target_combo.currentData() if stage.target_dimension_code is not None else None
        if stage.target_dimension_code is not None and target_detail_id is None:
            QMessageBox.warning(self, "خطا", f"ابتدا {stage.target_label or 'مقصد'} را انتخاب کنید.")
            return
        if stage.confirm_message:
            confirm = QMessageBox.question(self, "تاییدِ عملیات", stage.confirm_message, QMessageBox.Yes | QMessageBox.No)
            if confirm != QMessageBox.Yes:
                return
        user_id = session.current_user.user_id
        try:
            if stage.key == "TRANSFER":
                treasury_service.transfer_received_checks_between_funds(check_ids, company_id, user_id, target_detail_id)
            elif stage.key == "CASH_COLLECT":
                treasury_service.collect_received_checks_cash(check_ids, company_id, user_id, target_detail_id)
            elif stage.key == "BANK_DEPOSIT":
                treasury_service.deposit_received_checks_to_bank(check_ids, company_id, user_id, target_detail_id)
            elif stage.key == "BANK_CLEAR":
                treasury_service.clear_deposited_received_checks(check_ids, company_id, user_id)
            elif stage.key == "BANK_RETURN":
                treasury_service.return_deposited_received_checks_to_fund(check_ids, company_id, user_id, target_detail_id)
            elif stage.key == "CUSTOMER_RETURN":
                treasury_service.bounce_received_checks(check_ids, company_id, user_id)
            elif stage.key == "ENDORSED_RETURN":
                treasury_service.unendorse_received_checks_to_fund(check_ids, company_id, target_detail_id, user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _single_selected_check(self, action_title: str) -> "treasury_service.ReceivedCheckRow | None":
        """طبقِ گزارشِ صریح: کاربر عادت دارد چک را با تیکِ کنارِ ردیف انتخاب
        کند (همان مکانیزمِ «تاییدِ عملیات»)، نه حتماً با کلیک/هایلایتِ ردیف
        — پس این‌جا هم اول تیک‌خورده‌ها بررسی می‌شوند، و فقط اگر هیچ‌کدام
        تیک نخورده بود، سراغِ ردیفِ هایلایت‌شده (currentRow) می‌رویم."""
        checked_ids = self._checked_check_ids()
        if len(checked_ids) > 1:
            QMessageBox.information(self, action_title, "فقط یک چک را برایِ این عملیات تیک بزنید.")
            return None
        if len(checked_ids) == 1:
            return next((c for c in self._checks if c.received_check_id == checked_ids[0]), None)
        row_index = self.table.currentRow()
        if row_index < 0 or row_index >= len(self._filtered_checks):
            QMessageBox.information(self, action_title, "ابتدا یک چک را با تیکِ کنارِ ردیف یا کلیک انتخاب کنید.")
            return None
        return self._filtered_checks[row_index]

    def _show_history(self) -> None:
        check = self._single_selected_check("تاریخچه")
        if check is None:
            return
        dialog = _CheckHistoryDialog("RECEIVED", check.received_check_id, check.check_no, self)
        dialog.exec()
        if dialog.undo_performed:
            self.refresh()

    def _delete_check(self) -> None:
        check = self._single_selected_check("حذفِ چک")
        if check is None:
            return
        company_id = self._company_id()
        if company_id is None or session.current_user is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ چک",
            f"چکِ شماره‌ی {numerals.to_persian_digits(check.check_no)} به همراهِ سندِ ثبتِ اولیه‌اش کاملاً حذف شود؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            treasury_service.delete_received_check(check.received_check_id, company_id, session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()


class IssuedChecksScreen(FieldHelpMixin, QWidget):
    _COLUMNS = ["شماره‌یِ چک", "حسابِ بانکی", "گیرنده", "مبلغ", "سررسید"]
    _DATE_BASIS_OPTIONS = [("due_date", "سررسید"), ("issue_date", "تاریخِ صدور")]

    def __init__(self) -> None:
        super().__init__()
        self._checks: list[treasury_service.IssuedCheckRow] = []
        self._filtered_checks: list[treasury_service.IssuedCheckRow] = []
        self._stage: _StageConfig = _ISSUED_STAGES[0]

        # هم‌الگو با ReceivedChecksScreen (طبقِ آیتم‌هایِ ۱-۳): محتوایِ
        # متغیر داخلِ QScrollArea + کارت، دکمه‌هایِ عملیات در نوارِ ثابتِ
        # زیرِ اسکرول.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(10)

        title = QLabel("چک‌هایِ پرداختی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self._stage_group = QButtonGroup(self)
        stage_row = QHBoxLayout()
        stage_row.setSpacing(24)
        for index, stage in enumerate(_ISSUED_STAGES):
            radio = QRadioButton(stage.label)
            radio.setChecked(index == 0)
            radio.toggled.connect(lambda checked, s=stage: self._on_stage_selected(s) if checked else None)
            self._stage_group.addButton(radio)
            stage_row.addWidget(radio)
        stage_row.addStretch(1)
        layout.addLayout(stage_row)

        # طبقِ آیتمِ ۲: فیلترِ بازه‌یِ تاریخ (سررسید یا تاریخِ صدور) +
        # جست‌وجویِ طرفِ‌حساب (نامِ گیرنده).
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("مبنایِ فیلترِ تاریخ:"))
        self.date_basis_combo = QComboBox()
        for value, label in self._DATE_BASIS_OPTIONS:
            self.date_basis_combo.addItem(label, value)
        self.date_basis_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.date_basis_combo)
        self.date_filter_enabled = QCheckBox("فعال")
        self.date_filter_enabled.toggled.connect(self._apply_filters)
        filter_row.addWidget(self.date_filter_enabled)
        filter_row.addWidget(QLabel("از"))
        self.date_from_field = JalaliDateEdit()
        self.date_from_field.editingFinished.connect(self._apply_filters)
        filter_row.addWidget(self.date_from_field)
        filter_row.addWidget(QLabel("تا"))
        self.date_to_field = JalaliDateEdit()
        self.date_to_field.editingFinished.connect(self._apply_filters)
        filter_row.addWidget(self.date_to_field)
        filter_row.addWidget(QLabel("طرفِ‌حساب:"))
        self.counterparty_filter_field = QLineEdit()
        self.counterparty_filter_field.setPlaceholderText("جست‌وجو در نامِ گیرنده…")
        self.counterparty_filter_field.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.counterparty_filter_field, stretch=1)
        layout.addLayout(filter_row)

        # طبقِ آیتمِ ۶: «راسِ روز» — تاریخِ میانگینِ وزنیِ چک‌هایِ تیک‌خورده
        # (اگر چیزی تیک نخورده باشد، رویِ همه‌یِ چک‌هایِ فیلترشده‌یِ فعلی).
        self.ras_label = QLabel("")
        self.ras_label.setObjectName("raasLabel")
        layout.addWidget(self.ras_label)

        self.table = QTableWidget(0, len(self._COLUMNS) + 1)
        self.table.setHorizontalHeaderLabels([""] + self._COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 32)
        self.table.setMinimumHeight(240)
        self.table.cellDoubleClicked.connect(lambda *_: self._show_history())
        self.table.itemChanged.connect(lambda _item: self._update_ras_label())
        layout.addWidget(self.table, stretch=1)

        scroll.setWidget(panel)

        wrapper = QWidget()
        wrapper.setObjectName("card")
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(0)
        wrapper_layout.addWidget(scroll, stretch=1)

        self.history_button = QPushButton("🕒")
        self.history_button.setObjectName("iconButton")
        self.history_button.setFixedWidth(44)
        self.history_button.setToolTip("تاریخچه")
        self.history_button.clicked.connect(self._show_history)
        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذفِ چک")
        self.delete_button.clicked.connect(self._delete_check)
        self.confirm_button = QPushButton("✅")
        self.confirm_button.setObjectName("iconButton")
        self.confirm_button.setFixedWidth(44)
        self.confirm_button.setToolTip("تاییدِ عملیات")
        self.confirm_button.clicked.connect(self._apply_stage)
        footer = build_action_footer([self.history_button, self.delete_button, self.confirm_button])
        wrapper_layout.addWidget(footer)

        outer.addWidget(wrapper, stretch=1)

        self.status_label = QLabel("")
        outer.addWidget(self.status_label)

        self.set_field_help([
            (
                self.table,
                "بالا مرحله‌یِ موردِنظر را انتخاب کنید — فهرست به چک‌هایِ واجدِ شرایطِ همان مرحله به‌روز می‌شود؛ "
                "چک(ها) را تیک بزنید و «تاییدِ عملیات» را بزنید تا همه‌یِ چک‌هایِ تیک‌خورده یک‌جا پردازش شوند.",
            ),
        ])

        self._on_stage_selected(self._stage)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _on_stage_selected(self, stage: _StageConfig) -> None:
        self._stage = stage
        self.refresh()

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self._checks = []
            self.table.setRowCount(0)
            return
        self._checks = treasury_service.list_issued_checks(company_id, status_codes=list(self._stage.eligible_status_codes))
        self._apply_filters()

    def _apply_filters(self) -> None:
        """طبقِ آیتمِ ۲: فیلترِ بازه‌یِ تاریخ (سررسید یا تاریخِ صدور) +
        جست‌وجویِ طرفِ‌حساب — رویِ self._checksِ از قبل واکشی‌شده."""
        query = self.counterparty_filter_field.text().strip().lower()
        use_date_filter = self.date_filter_enabled.isChecked()
        basis = self.date_basis_combo.currentData() or "due_date"
        date_from = self.date_from_field.date() if use_date_filter else None
        date_to = self.date_to_field.date() if use_date_filter else None

        self._filtered_checks = []
        for c in self._checks:
            if query and query not in (c.payee_name or "").lower():
                continue
            if use_date_filter:
                check_date = c.due_date if basis == "due_date" else c.issue_date
                if date_from is not None and check_date < date_from:
                    continue
                if date_to is not None and check_date > date_to:
                    continue
            self._filtered_checks.append(c)

        self.table.setRowCount(len(self._filtered_checks))
        for row_index, c in enumerate(self._filtered_checks):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Unchecked)
            check_item.setData(Qt.UserRole, c.issued_check_id)
            self.table.setItem(row_index, 0, check_item)
            values = [
                c.check_no,
                c.bank_account_label or "—",
                c.payee_name or "—",
                numerals.format_money(c.amount, 0, None),
                numerals.format_jalali_date(c.due_date),
            ]
            for col_index, value in enumerate(values, start=1):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
        self._update_ras_label()

    def _update_ras_label(self) -> None:
        """طبقِ آیتمِ ۶: «راسِ روز» — رویِ چک‌هایِ تیک‌خورده (اگر چیزی
        تیک نخورده، رویِ همه‌ی چک‌هایِ فیلترشده‌یِ فعلی)."""
        checked_ids = set(self._checked_check_ids())
        subset = [c for c in self._filtered_checks if c.issued_check_id in checked_ids] if checked_ids else self._filtered_checks
        if not subset:
            self.ras_label.setText("")
            return
        ras_date, total = treasury_service.compute_check_ras([(c.amount, c.due_date) for c in subset])
        scope_word = "چک‌هایِ تیک‌خورده" if checked_ids else "همه‌ی چک‌هایِ نمایش‌داده‌شده"
        self.ras_label.setText(
            f"راسِ روز ({scope_word}): {numerals.format_jalali_date(ras_date)}    —    "
            f"جمعِ مبلغ: {numerals.format_money(total, 0, None)}"
        )

    def _checked_check_ids(self) -> list[int]:
        ids = []
        for row_index in range(self.table.rowCount()):
            item = self.table.item(row_index, 0)
            if item is not None and item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def _apply_stage(self) -> None:
        company_id = self._company_id()
        check_ids = self._checked_check_ids()
        if company_id is None or session.current_user is None or not check_ids:
            return
        stage = self._stage
        if stage.confirm_message:
            confirm = QMessageBox.question(self, "تاییدِ عملیات", stage.confirm_message, QMessageBox.Yes | QMessageBox.No)
            if confirm != QMessageBox.Yes:
                return
        user_id = session.current_user.user_id
        try:
            if stage.key == "BANK_CLEAR":
                treasury_service.clear_issued_checks(check_ids, company_id, user_id)
            elif stage.key == "RETURN_TO_FUND":
                treasury_service.return_issued_checks_to_fund(check_ids, company_id, user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _single_selected_check(self, action_title: str) -> "treasury_service.IssuedCheckRow | None":
        """طبقِ گزارشِ صریح: کاربر عادت دارد چک را با تیکِ کنارِ ردیف انتخاب
        کند (همان مکانیزمِ «تاییدِ عملیات»)، نه حتماً با کلیک/هایلایتِ ردیف
        — پس این‌جا هم اول تیک‌خورده‌ها بررسی می‌شوند، و فقط اگر هیچ‌کدام
        تیک نخورده بود، سراغِ ردیفِ هایلایت‌شده (currentRow) می‌رویم."""
        checked_ids = self._checked_check_ids()
        if len(checked_ids) > 1:
            QMessageBox.information(self, action_title, "فقط یک چک را برایِ این عملیات تیک بزنید.")
            return None
        if len(checked_ids) == 1:
            return next((c for c in self._checks if c.issued_check_id == checked_ids[0]), None)
        row_index = self.table.currentRow()
        if row_index < 0 or row_index >= len(self._filtered_checks):
            QMessageBox.information(self, action_title, "ابتدا یک چک را با تیکِ کنارِ ردیف یا کلیک انتخاب کنید.")
            return None
        return self._filtered_checks[row_index]

    def _show_history(self) -> None:
        check = self._single_selected_check("تاریخچه")
        if check is None:
            return
        dialog = _CheckHistoryDialog("ISSUED", check.issued_check_id, check.check_no, self)
        dialog.exec()
        if dialog.undo_performed:
            self.refresh()

    def _delete_check(self) -> None:
        check = self._single_selected_check("حذفِ چک")
        if check is None:
            return
        company_id = self._company_id()
        if company_id is None or session.current_user is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ چک",
            f"چکِ شماره‌ی {numerals.to_persian_digits(check.check_no)} به همراهِ سندِ ثبتِ اولیه‌اش کاملاً حذف شود؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            treasury_service.delete_issued_check(check.issued_check_id, company_id, session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()
