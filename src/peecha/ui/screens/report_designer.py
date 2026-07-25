"""طراحیِ گزارش‌سازِ کامل — گزارش‌سازِ ستون+ردیف: یا DETAIL (سطحِ سطرِ سند،
ستون از یک کاتالوگِ ثابت + فیلترِ حسابیِ اختیاری، مثلِ دفترِ روزنامه/کل با
ستون‌هایِ دلخواه) یا SUMMARY (چند ستونِ مقدار/دوره رویِ ردیف‌هایِ یک الگویِ
حسابیِ موجود که در «طراحیِ الگویِ گزارش» ساخته می‌شود، مثلِ ترازِ چندستونی
یا مقایسه‌یِ چند دوره).

چیدمانِ master-detail هم‌الگو با statement_template_designer.py."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import report_designer as report_designer_service
from peecha.services import statement_templates as statement_templates_service
from peecha.services.report_designer import AccountFilterInfo, ReportColumnInfo
from peecha.ui import theme
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit

_KIND_OPTIONS = [("DETAIL", "تراکنشی (سطحِ سطرِ سند)"), ("SUMMARY", "خلاصه (رویِ یک الگویِ حسابی)")]
_KIND_LABELS = dict(_KIND_OPTIONS)

_DETAIL_FIELD_OPTIONS = [
    ("DOCUMENT_DATE", "تاریخِ سند"),
    ("DOCUMENT_NO", "شماره‌یِ سند"),
    ("ALT_NUMBER", "شماره‌یِ جایگزین"),
    ("DESCRIPTION", "شرح"),
    ("ACCOUNT_CODE", "کدِ حساب"),
    ("ACCOUNT_NAME", "نامِ حساب"),
    ("DETAIL_NAMES", "تفصیلی‌ها"),
    ("DEBIT", "بدهکار"),
    ("CREDIT", "بستانکار"),
    ("RUNNING_BALANCE", "مانده‌یِ رواگرد"),
    ("STATUS", "وضعیتِ سند"),
]
_DETAIL_FIELD_LABELS = dict(_DETAIL_FIELD_OPTIONS)

_SUMMARY_MEASURE_OPTIONS = [
    ("OPENING_BALANCE", "مانده‌یِ اول"),
    ("PERIOD_DEBIT", "بدهکارِ دوره"),
    ("PERIOD_CREDIT", "بستانکارِ دوره"),
    ("CLOSING_BALANCE", "مانده‌یِ آخر"),
    ("NATURAL_BALANCE", "مبلغ (علامتِ طبیعی)"),
]
_SUMMARY_MEASURE_LABELS = dict(_SUMMARY_MEASURE_OPTIONS)

_ACCOUNT_SELECTOR_OPTIONS = [
    ("ACCOUNT", "حسابِ مشخص"),
    ("RANGE", "بازه‌یِ کد"),
    ("CATEGORY", "طبقه‌یِ حساب"),
]
_ACCOUNT_LEVEL_OPTIONS = [(1, "گروه"), (2, "کل"), (3, "معین"), (4, "تفصیلی")]
_ACCOUNT_LEVEL_LABELS = dict(_ACCOUNT_LEVEL_OPTIONS)
_CATEGORY_OPTIONS = [
    ("ASSET", "دارایی"),
    ("LIABILITY", "بدهی"),
    ("EQUITY", "حقوق صاحبان سهام"),
    ("REVENUE", "درآمد"),
    ("EXPENSE", "هزینه"),
]
_CATEGORY_LABELS = dict(_CATEGORY_OPTIONS)

_COLUMN_TABLE_HEADERS = ["منبعِ ستون", "برچسب", ""]


class _AccountFilterListWidget(QWidget):
    """لیستِ فیلترهایِ حسابیِ گزارشِ تراکنشی — هرکدام حسابِ مشخص/بازه/طبقه؛
    بدونِ علامتِ +/− (فقط فیلترِ عضویت است، نه جمع/تفریق). لیستِ خالی یعنی
    همه‌یِ حساب‌هایِ قابلِ ثبت."""

    def __init__(self) -> None:
        super().__init__()
        self._filters: list[AccountFilterInfo] = []
        self._options_by_id: dict[int, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("نوع:"))
        self.selector_type_combo = QComboBox()
        for code, label in _ACCOUNT_SELECTOR_OPTIONS:
            self.selector_type_combo.addItem(label, code)
        self.selector_type_combo.currentIndexChanged.connect(self._on_selector_type_changed)
        type_row.addWidget(self.selector_type_combo)
        layout.addLayout(type_row)

        self.account_combo = QComboBox()
        self.account_combo.setEditable(True)
        self.account_combo.addItem("", None)
        layout.addWidget(self.account_combo)

        range_row = QHBoxLayout()
        self.level_combo = QComboBox()
        for level, label in _ACCOUNT_LEVEL_OPTIONS:
            self.level_combo.addItem(label, level)
        range_row.addWidget(self.level_combo)
        self.code_from_field = QLineEdit()
        self.code_from_field.setPlaceholderText("از کدِ...")
        range_row.addWidget(self.code_from_field)
        self.code_to_field = QLineEdit()
        self.code_to_field.setPlaceholderText("تا کدِ...")
        range_row.addWidget(self.code_to_field)
        layout.addLayout(range_row)

        self.category_combo = QComboBox()
        for code, label in _CATEGORY_OPTIONS:
            self.category_combo.addItem(label, code)
        layout.addWidget(self.category_combo)

        add_button = QPushButton("افزودن")
        add_button.setObjectName("flatButton")
        add_button.clicked.connect(self._on_add)
        layout.addWidget(add_button)

        self.list_widget = QListWidget()
        self.list_widget.setMaximumHeight(90)
        layout.addWidget(self.list_widget)

        remove_button = QPushButton("حذفِ موردِ انتخاب‌شده")
        remove_button.setObjectName("flatButton")
        remove_button.clicked.connect(self._on_remove_selected)
        layout.addWidget(remove_button)

        self._on_selector_type_changed()

    def set_account_options(self, options: list[tuple[int, str]]) -> None:
        self._options_by_id = dict(options)
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItem("", None)
        for account_id, label in options:
            self.account_combo.addItem(label, account_id)
        completer = QCompleter([label for _id, label in options])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.account_combo.setCompleter(completer)
        self.account_combo.blockSignals(False)

    def _on_selector_type_changed(self) -> None:
        selector_type = self.selector_type_combo.currentData()
        self.account_combo.setVisible(selector_type == "ACCOUNT")
        for widget in (self.level_combo, self.code_from_field, self.code_to_field):
            widget.setVisible(selector_type == "RANGE")
        self.category_combo.setVisible(selector_type == "CATEGORY")
        if selector_type == "CATEGORY":
            self.level_combo.setVisible(True)

    def _describe(self, f: AccountFilterInfo) -> str:
        if f.selector_type == "RANGE":
            level_label = _ACCOUNT_LEVEL_LABELS.get(f.account_level, "")
            return f"بازه ({level_label}): {f.code_from} تا {f.code_to}"
        if f.selector_type == "CATEGORY":
            level_label = _ACCOUNT_LEVEL_LABELS.get(f.account_level, "")
            category_label = _CATEGORY_LABELS.get(f.category_code, f.category_code)
            return f"طبقه ({level_label}): {category_label}"
        return self._options_by_id.get(f.account_id, str(f.account_id))

    def _on_add(self) -> None:
        selector_type = self.selector_type_combo.currentData()
        if selector_type == "ACCOUNT":
            account_id = self.account_combo.currentData()
            if account_id is None:
                return
            self._filters.append(AccountFilterInfo(selector_type="ACCOUNT", account_id=account_id))
        elif selector_type == "RANGE":
            code_from = self.code_from_field.text().strip()
            code_to = self.code_to_field.text().strip()
            if not code_from or not code_to:
                return
            self._filters.append(
                AccountFilterInfo(
                    selector_type="RANGE",
                    account_level=self.level_combo.currentData(),
                    code_from=code_from,
                    code_to=code_to,
                )
            )
        else:  # CATEGORY
            self._filters.append(
                AccountFilterInfo(
                    selector_type="CATEGORY",
                    account_level=self.level_combo.currentData(),
                    category_code=self.category_combo.currentData(),
                )
            )
        self._refresh_list()

    def _on_remove_selected(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        del self._filters[row]
        self._refresh_list()

    def _refresh_list(self) -> None:
        self.list_widget.clear()
        for f in self._filters:
            self.list_widget.addItem(self._describe(f))

    def set_filters(self, filters: list[AccountFilterInfo]) -> None:
        self._filters = list(filters)
        self._refresh_list()

    def filters(self) -> list[AccountFilterInfo]:
        return list(self._filters)


class _ColumnEditorDialog(QDialog):
    def __init__(self, report_kind: str, existing: ReportColumnInfo | None = None) -> None:
        super().__init__()
        self.report_kind = report_kind
        self.setWindowTitle("ویرایشِ ستون" if existing else "افزودنِ ستون")
        self.resize(420, 340)

        layout = QVBoxLayout(self)

        if report_kind == "DETAIL":
            layout.addWidget(QLabel("فیلد:"))
            self.field_combo = QComboBox()
            for code, label in _DETAIL_FIELD_OPTIONS:
                self.field_combo.addItem(label, code)
            self.field_combo.currentIndexChanged.connect(self._on_source_changed)
            layout.addWidget(self.field_combo)
        else:
            layout.addWidget(QLabel("نوعِ مقدار:"))
            self.measure_combo = QComboBox()
            for code, label in _SUMMARY_MEASURE_OPTIONS:
                self.measure_combo.addItem(label, code)
            self.measure_combo.currentIndexChanged.connect(self._on_source_changed)
            layout.addWidget(self.measure_combo)

            self.date_override_checkbox = QCheckBox("بازه‌یِ تاریخِ اختصاصی برایِ این ستون")
            self.date_override_checkbox.toggled.connect(self._on_date_override_toggled)
            layout.addWidget(self.date_override_checkbox)

            date_row = QHBoxLayout()
            date_row.addWidget(QLabel("از:"))
            self.date_from_field = JalaliDateEdit()
            date_row.addWidget(self.date_from_field)
            date_row.addWidget(QLabel("تا:"))
            self.date_to_field = JalaliDateEdit()
            date_row.addWidget(self.date_to_field)
            layout.addLayout(date_row)
            self.date_from_field.setEnabled(False)
            self.date_to_field.setEnabled(False)

        layout.addWidget(QLabel("برچسبِ ستون:"))
        self.label_field = QLineEdit()
        self._label_user_edited = False
        self.label_field.textEdited.connect(self._on_label_edited)
        layout.addWidget(self.label_field)

        layout.addStretch(1)
        self.error_label = QLabel("")
        self.error_label.setObjectName("statusError")
        layout.addWidget(self.error_label)

        buttons_row = QHBoxLayout()
        buttons_row.addStretch(1)
        cancel_button = QPushButton("انصراف")
        cancel_button.clicked.connect(self.reject)
        buttons_row.addWidget(cancel_button)
        save_button = QPushButton("ذخیره")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._on_save_clicked)
        buttons_row.addWidget(save_button)
        layout.addLayout(buttons_row)

        if existing is not None:
            if report_kind == "DETAIL":
                index = self.field_combo.findData(existing.field_code)
                self.field_combo.setCurrentIndex(index if index >= 0 else 0)
            else:
                index = self.measure_combo.findData(existing.measure_code)
                self.measure_combo.setCurrentIndex(index if index >= 0 else 0)
                if existing.date_from_override or existing.date_to_override:
                    self.date_override_checkbox.setChecked(True)
                    if existing.date_from_override:
                        self.date_from_field.setDate(existing.date_from_override)
                    if existing.date_to_override:
                        self.date_to_field.setDate(existing.date_to_override)
            self.label_field.setText(existing.label)
            # ویرایشِ ردیفِ موجود: برچسبِ ذخیره‌شده ممکن است دستی انتخاب
            # شده باشد — با تغییرِ بعدیِ فیلد/نوعِ مقدار در همین دیالوگ نباید
            # بی‌سروصدا بازنویسی شود.
            self._label_user_edited = True
        else:
            self._on_source_changed()

    def _on_label_edited(self, _text: str) -> None:
        self._label_user_edited = True

    def _on_date_override_toggled(self, checked: bool) -> None:
        self.date_from_field.setEnabled(checked)
        self.date_to_field.setEnabled(checked)

    def _on_source_changed(self) -> None:
        if self._label_user_edited:
            return
        if self.report_kind == "DETAIL":
            code = self.field_combo.currentData()
            default_label = _DETAIL_FIELD_LABELS.get(code, "")
        else:
            code = self.measure_combo.currentData()
            default_label = _SUMMARY_MEASURE_LABELS.get(code, "")
        self.label_field.setText(default_label)

    def _on_save_clicked(self) -> None:
        if not self.label_field.text().strip():
            theme.set_status_label(self.error_label, "برچسبِ ستون را وارد کنید.", ok=False)
            return
        self.accept()

    def result_column(self, column_order: int) -> ReportColumnInfo:
        if self.report_kind == "DETAIL":
            return ReportColumnInfo(
                column_id=0,
                column_order=column_order,
                label=self.label_field.text().strip(),
                field_code=self.field_combo.currentData(),
            )
        date_from = self.date_from_field.date() if self.date_override_checkbox.isChecked() else None
        date_to = self.date_to_field.date() if self.date_override_checkbox.isChecked() else None
        return ReportColumnInfo(
            column_id=0,
            column_order=column_order,
            label=self.label_field.text().strip(),
            measure_code=self.measure_combo.currentData(),
            date_from_override=date_from,
            date_to_override=date_to,
        )


class ReportDesignerScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._templates: list[report_designer_service.ReportTemplateRow] = []
        self._columns: list[ReportColumnInfo] = []
        self._selected_template_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_templates_panel())
        outer.addWidget(self._build_detail_panel(), stretch=1)

        self.set_field_help([
            (self.new_name_field, "نامِ گزارشِ تازه‌ای که می‌خواهید بسازید."),
            (
                self.new_kind_combo,
                "«تراکنشی» یعنی یک سطر به‌ازایِ هر سطرِ سند (مثلِ دفترِ روزنامه/کل)، با ستون‌هایِ دلخواه. "
                "«خلاصه» یعنی چند ستونِ مقدار رویِ ردیف‌هایِ یک الگویِ حسابیِ موجود (مثلِ ترازِ چندستونی).",
            ),
            (
                self.new_statement_combo,
                "برایِ گزارشِ «خلاصه»، کدام الگویِ حسابی (از «طراحیِ الگویِ گزارش») مبنایِ ردیف‌ها باشد.",
            ),
            (
                self.templates_list,
                "فهرستِ گزارش‌سازهایِ ساخته‌شده. رویِ هرکدام کلیک کنید تا ستون‌ها و فیلترهایش را در سمتِ راست ببینید.",
            ),
        ])

    def _build_templates_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMaximumWidth(320)
        layout = QVBoxLayout(panel)

        title = QLabel("گزارش‌سازِ کامل")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.new_name_field = QLineEdit()
        self.new_name_field.setPlaceholderText("نامِ گزارشِ تازه...")
        layout.addWidget(self.new_name_field)

        self.new_kind_combo = QComboBox()
        for code, label in _KIND_OPTIONS:
            self.new_kind_combo.addItem(label, code)
        self.new_kind_combo.currentIndexChanged.connect(self._on_new_kind_changed)
        layout.addWidget(self.new_kind_combo)

        self.new_statement_label = QLabel("الگویِ حسابیِ مبنا:")
        layout.addWidget(self.new_statement_label)
        self.new_statement_combo = QComboBox()
        layout.addWidget(self.new_statement_combo)

        self.new_group_by_account_checkbox = QCheckBox("جمعِ فرعیِ زیرِ هر حساب (مانندِ دفترِ کل)")
        layout.addWidget(self.new_group_by_account_checkbox)

        add_template_button = QPushButton("افزودنِ گزارش")
        add_template_button.setObjectName("primaryButton")
        add_template_button.clicked.connect(self._on_add_template)
        layout.addWidget(add_template_button)

        self.templates_list = QListWidget()
        self.templates_list.currentRowChanged.connect(self._on_template_selected)
        layout.addWidget(self.templates_list, stretch=1)

        rename_row = QHBoxLayout()
        self.rename_field = QLineEdit()
        rename_row.addWidget(self.rename_field, stretch=1)
        rename_button = QPushButton("تغییرِ نام")
        rename_button.setObjectName("flatButton")
        rename_button.clicked.connect(self._on_rename_template)
        rename_row.addWidget(rename_button)
        layout.addLayout(rename_row)

        delete_template_button = QPushButton("حذفِ گزارش")
        delete_template_button.setObjectName("dangerButton")
        delete_template_button.clicked.connect(self._on_delete_template)
        layout.addWidget(delete_template_button)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        self._on_new_kind_changed()
        return panel

    def _on_new_kind_changed(self) -> None:
        is_summary = self.new_kind_combo.currentData() == "SUMMARY"
        self.new_statement_label.setVisible(is_summary)
        self.new_statement_combo.setVisible(is_summary)
        self.new_group_by_account_checkbox.setVisible(not is_summary)

    def _build_detail_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.detail_title = QLabel("یک گزارش انتخاب کنید")
        self.detail_title.setObjectName("sectionHint")
        layout.addWidget(self.detail_title)

        self.group_by_account_checkbox = QCheckBox("جمعِ فرعیِ زیرِ هر حساب (مانندِ دفترِ کل)")
        self.group_by_account_checkbox.toggled.connect(self._on_group_by_account_toggled)
        layout.addWidget(self.group_by_account_checkbox)

        layout.addWidget(QLabel("ستون‌ها:"))
        self.columns_table = QTableWidget(0, len(_COLUMN_TABLE_HEADERS))
        self.columns_table.setHorizontalHeaderLabels(_COLUMN_TABLE_HEADERS)
        self.columns_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.columns_table.verticalHeader().setVisible(False)
        self.columns_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.columns_table)

        add_column_button = QPushButton("افزودنِ ستون")
        add_column_button.setObjectName("primaryButton")
        add_column_button.clicked.connect(self._on_add_column)
        layout.addWidget(add_column_button)

        self.filters_label = QLabel("فیلترِ حساب‌ها (خالی = همه‌یِ حساب‌هایِ قابلِ ثبت):")
        layout.addWidget(self.filters_label)
        self.filters_widget = _AccountFilterListWidget()
        layout.addWidget(self.filters_widget)
        save_filters_button = QPushButton("ذخیره‌یِ فیلترِ حساب‌ها")
        save_filters_button.setObjectName("flatButton")
        save_filters_button.clicked.connect(self._on_save_filters)
        layout.addWidget(save_filters_button)

        layout.addStretch(1)
        return panel

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        theme.set_status_label(self.status_label, "", ok=True)
        company_id = self._company_id()

        self.new_statement_combo.clear()
        if company_id is not None:
            for t in statement_templates_service.list_templates(company_id):
                self.new_statement_combo.addItem(t.name, t.template_id)

        account_options = (
            [(a.account_id, f"{a.full_code} — {a.name}") for a in coa_service.list_accounts(company_id)]
            if company_id is not None
            else []
        )
        self.filters_widget.set_account_options(account_options)

        self._templates = report_designer_service.list_templates(company_id) if company_id is not None else []
        self.templates_list.blockSignals(True)
        self.templates_list.clear()
        for t in self._templates:
            self.templates_list.addItem(f"{t.name} ({_KIND_LABELS.get(t.report_kind, t.report_kind)})")
        self.templates_list.blockSignals(False)
        if self._templates:
            keep_index = next(
                (i for i, t in enumerate(self._templates) if t.report_template_id == self._selected_template_id), 0
            )
            self.templates_list.setCurrentRow(keep_index)
            self._on_template_selected(keep_index)
        else:
            self._selected_template_id = None
            self.rename_field.setText("")
            self._reload_columns()

    def _selected_template(self) -> report_designer_service.ReportTemplateRow | None:
        return next((t for t in self._templates if t.report_template_id == self._selected_template_id), None)

    def _on_template_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._templates):
            self._selected_template_id = None
            self.rename_field.setText("")
        else:
            self._selected_template_id = self._templates[row].report_template_id
            self.rename_field.setText(self._templates[row].name)
        self._reload_columns()

    def _reload_columns(self) -> None:
        template = self._selected_template()
        if template is None:
            self.detail_title.setText("یک گزارش انتخاب کنید")
            self.group_by_account_checkbox.setVisible(False)
            self.filters_label.setVisible(False)
            self.filters_widget.setVisible(False)
            self._columns = []
            self.columns_table.setRowCount(0)
            return

        is_detail = template.report_kind == "DETAIL"
        self.detail_title.setText(f"{template.name} — {_KIND_LABELS.get(template.report_kind, template.report_kind)}")
        self.group_by_account_checkbox.setVisible(is_detail)
        self.group_by_account_checkbox.blockSignals(True)
        self.group_by_account_checkbox.setChecked(template.group_by_account)
        self.group_by_account_checkbox.blockSignals(False)
        self.filters_label.setVisible(is_detail)
        self.filters_widget.setVisible(is_detail)
        if is_detail:
            self.filters_widget.set_filters(report_designer_service.list_account_filters(template.report_template_id))

        self._columns = report_designer_service.list_columns(template.report_template_id)
        self.columns_table.setRowCount(len(self._columns))
        for i, col in enumerate(self._columns):
            source_label = (
                _DETAIL_FIELD_LABELS.get(col.field_code, col.field_code or "")
                if is_detail
                else _SUMMARY_MEASURE_LABELS.get(col.measure_code, col.measure_code or "")
            )
            self.columns_table.setItem(i, 0, QTableWidgetItem(source_label))
            self.columns_table.setItem(i, 1, QTableWidgetItem(col.label))
            self.columns_table.setCellWidget(i, 2, self._build_column_actions(i))

    def _build_column_actions(self, index: int) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(2, 0, 2, 0)

        up_button = QPushButton("▲")
        up_button.setFixedWidth(28)
        up_button.clicked.connect(lambda _checked=False, i=index: self._on_move_column(i, -1))
        cell_layout.addWidget(up_button)

        down_button = QPushButton("▼")
        down_button.setFixedWidth(28)
        down_button.clicked.connect(lambda _checked=False, i=index: self._on_move_column(i, 1))
        cell_layout.addWidget(down_button)

        edit_button = QPushButton("ویرایش")
        edit_button.setObjectName("flatButton")
        edit_button.clicked.connect(lambda _checked=False, i=index: self._on_edit_column(i))
        cell_layout.addWidget(edit_button)

        delete_button = QPushButton("حذف")
        delete_button.setObjectName("dangerButton")
        delete_button.clicked.connect(lambda _checked=False, i=index: self._on_delete_column(i))
        cell_layout.addWidget(delete_button)

        return cell

    def _persist_columns(self) -> None:
        if self._selected_template_id is None:
            return
        report_designer_service.set_columns(self._selected_template_id, self._columns)
        self._reload_columns()

    def _on_add_template(self) -> None:
        company_id = self._company_id()
        name = self.new_name_field.text().strip()
        if company_id is None or not name:
            return
        kind = self.new_kind_combo.currentData()
        if kind == "SUMMARY":
            statement_template_id = self.new_statement_combo.currentData()
            if statement_template_id is None:
                theme.set_status_label(self.status_label, "ابتدا یک الگویِ حسابیِ مبنا انتخاب کنید.", ok=False)
                return
            report_designer_service.create_template(
                company_id, name, "SUMMARY", statement_template_id=statement_template_id
            )
        else:
            report_designer_service.create_template(
                company_id, name, "DETAIL", group_by_account=self.new_group_by_account_checkbox.isChecked()
            )
        self.new_name_field.clear()
        self.refresh()

    def _on_rename_template(self) -> None:
        if self._selected_template_id is None:
            return
        name = self.rename_field.text().strip()
        if not name:
            return
        report_designer_service.rename_template(self._selected_template_id, name)
        self.refresh()

    def _on_delete_template(self) -> None:
        if self._selected_template_id is None:
            return
        report_designer_service.delete_template(self._selected_template_id)
        self._selected_template_id = None
        self.refresh()

    def _on_add_column(self) -> None:
        template = self._selected_template()
        if template is None:
            theme.set_status_label(self.status_label, "ابتدا یک گزارش انتخاب/بسازید.", ok=False)
            return
        dialog = _ColumnEditorDialog(template.report_kind)
        if dialog.exec() != QDialog.Accepted:
            return
        self._columns.append(dialog.result_column(len(self._columns) + 1))
        self._persist_columns()

    def _on_edit_column(self, index: int) -> None:
        template = self._selected_template()
        if template is None or index >= len(self._columns):
            return
        dialog = _ColumnEditorDialog(template.report_kind, existing=self._columns[index])
        if dialog.exec() != QDialog.Accepted:
            return
        self._columns[index] = dialog.result_column(index + 1)
        self._persist_columns()

    def _on_delete_column(self, index: int) -> None:
        if index >= len(self._columns):
            return
        del self._columns[index]
        self._persist_columns()

    def _on_move_column(self, index: int, direction: int) -> None:
        new_index = index + direction
        if new_index < 0 or new_index >= len(self._columns):
            return
        self._columns[index], self._columns[new_index] = self._columns[new_index], self._columns[index]
        self._persist_columns()

    def _on_group_by_account_toggled(self, checked: bool) -> None:
        if self._selected_template_id is None:
            return
        template = self._selected_template()
        if template is None or template.report_kind != "DETAIL":
            return
        report_designer_service.set_group_by_account(self._selected_template_id, checked)
        self.refresh()

    def _on_save_filters(self) -> None:
        if self._selected_template_id is None:
            return
        report_designer_service.set_account_filters(self._selected_template_id, self.filters_widget.filters())
        theme.set_status_label(self.status_label, "فیلترِ حساب‌ها ذخیره شد.", ok=True)
