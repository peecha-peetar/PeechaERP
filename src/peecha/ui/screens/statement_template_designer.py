"""طراحِ الگویِ گزارشِ سفارشی (فازِ ۲) — «محیطِ ساختن»یِ درخواست‌شده برایِ
اینکه صورتِ سود-زیان/ترازنامه/هرگزارشِ دیگر از رویِ اقلامِ ترکیبی (چند
حسابِ دلخواه در هر سطحی: گروه/کل/معین، یا جمعِ چند ردیفِ دیگر) ساخته
شود — مثلاً «موجودیِ اولِ دوره + خریدِ طیِ دوره» به‌عنوانِ یک قلم.

چیدمانِ master-detail هم‌الگو با dimension_group_config.py: پنلِ چپ
فهرستِ الگوها، پنلِ راست جدولِ ردیف‌هایِ الگویِ انتخاب‌شده."""

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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import statement_templates as statement_templates_service
from peecha.services.statement_templates import AccountRefInfo
from peecha.ui import theme
from peecha.ui.widgets import FieldHelpMixin, wrap_scrollable

_STATEMENT_TYPE_OPTIONS = [
    ("CUSTOM", "سفارشی"),
    ("INCOME_STATEMENT", "سود و زیان"),
    ("BALANCE_SHEET", "ترازنامه"),
    ("CASH_FLOW", "گردشِ وجوهِ نقد"),
]
_STATEMENT_TYPE_LABELS = dict(_STATEMENT_TYPE_OPTIONS)

_ROW_TYPE_OPTIONS = [
    ("HEADER", "سرتیتر (بدونِ مبلغ)"),
    ("ACCOUNTS", "اقلامِ حساب (جمعِ چند حساب)"),
    ("FORMULA", "فرمول (جمعِ چند ردیفِ دیگر)"),
]
_ROW_TYPE_LABELS = dict(_ROW_TYPE_OPTIONS)

_ROW_COLUMNS = ["نوع", "برچسب", "تورفتگی", "بولد", ""]

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
    ("COGS", "بهایِ تمام‌شده"),
    ("EXPENSE", "هزینه"),
    ("STATISTICAL", "حساب‌هایِ آماری"),
]
_CATEGORY_LABELS = dict(_CATEGORY_OPTIONS)


class _RefListWidget(QWidget):
    """لیستِ اقلامِ انتخاب‌شده (حساب یا ردیفِ ارجاعی) با علامتِ +/− و حذف —
    برایِ هردو حالتِ ACCOUNTS و FORMULA در دیالوگِ ویرایشِ ردیف استفاده
    می‌شود (فقط گزینه‌هایِ combo فرق می‌کنند، منطق یکی است)."""

    def __init__(self, options: list[tuple[int, str]]) -> None:
        super().__init__()
        self._refs: list[tuple[int, int]] = []
        self._options_by_id = dict(options)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        add_row = QHBoxLayout()
        self.picker_combo = QComboBox()
        self.picker_combo.setEditable(True)
        self.picker_combo.addItem("", None)
        for id_, label in options:
            self.picker_combo.addItem(label, id_)
        completer = QCompleter([label for _id, label in options])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.picker_combo.setCompleter(completer)
        add_row.addWidget(self.picker_combo, stretch=1)

        self.sign_combo = QComboBox()
        self.sign_combo.addItem("جمع (+)", 1)
        self.sign_combo.addItem("کسر (−)", -1)
        add_row.addWidget(self.sign_combo)

        add_button = QPushButton("➕")
        add_button.setObjectName("iconButton")
        add_button.setFixedWidth(44)
        add_button.setToolTip("افزودن")
        add_button.clicked.connect(self._on_add)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        self.list_widget = QListWidget()
        self.list_widget.setMaximumHeight(110)
        layout.addWidget(self.list_widget)

        remove_button = QPushButton("🗑️")
        remove_button.setObjectName("dangerIconButton")
        remove_button.setFixedWidth(44)
        remove_button.setToolTip("حذفِ موردِ انتخاب‌شده")
        remove_button.clicked.connect(self._on_remove_selected)
        layout.addWidget(remove_button)

    def _on_add(self) -> None:
        ref_id = self.picker_combo.currentData()
        if ref_id is None:
            return
        if any(existing_id == ref_id for existing_id, _sign in self._refs):
            return
        self._refs.append((ref_id, self.sign_combo.currentData()))
        self._refresh_list()

    def _on_remove_selected(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        del self._refs[row]
        self._refresh_list()

    def _refresh_list(self) -> None:
        self.list_widget.clear()
        for ref_id, sign in self._refs:
            sign_label = "+" if sign == 1 else "−"
            label = self._options_by_id.get(ref_id, str(ref_id))
            self.list_widget.addItem(f"{sign_label}  {label}")

    def set_refs(self, refs: list[tuple[int, int]]) -> None:
        self._refs = list(refs)
        self._refresh_list()

    def refs(self) -> list[tuple[int, int]]:
        return list(self._refs)


class _AccountRefListWidget(QWidget):
    """لیستِ اجزایِ حسابیِ یک ردیفِ ACCOUNTS — گزارش‌سازِ پیشرفته: هر جزء
    یا یک حسابِ مشخص، یا یک بازه‌یِ کد در یک سطح، یا کلِ یک طبقه (دارایی/
    بدهی/...) در یک سطح است؛ کنترل‌هایِ ورودی بسته به نوعِ انتخابی
    نمایش/مخفی می‌شوند."""

    def __init__(self, account_options: list[tuple[int, str]]) -> None:
        super().__init__()
        self._refs: list[AccountRefInfo] = []

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
        for account_id, label in account_options:
            self.account_combo.addItem(label, account_id)
        completer = QCompleter([label for _id, label in account_options])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.account_combo.setCompleter(completer)
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

        add_row = QHBoxLayout()
        self.sign_combo = QComboBox()
        self.sign_combo.addItem("جمع (+)", 1)
        self.sign_combo.addItem("کسر (−)", -1)
        add_row.addWidget(self.sign_combo)
        add_button = QPushButton("➕")
        add_button.setObjectName("iconButton")
        add_button.setFixedWidth(44)
        add_button.setToolTip("افزودن")
        add_button.clicked.connect(self._on_add)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        self.list_widget = QListWidget()
        self.list_widget.setMaximumHeight(110)
        layout.addWidget(self.list_widget)

        remove_button = QPushButton("🗑️")
        remove_button.setObjectName("dangerIconButton")
        remove_button.setFixedWidth(44)
        remove_button.setToolTip("حذفِ موردِ انتخاب‌شده")
        remove_button.clicked.connect(self._on_remove_selected)
        layout.addWidget(remove_button)

        self._on_selector_type_changed()

    def _on_selector_type_changed(self) -> None:
        selector_type = self.selector_type_combo.currentData()
        self.account_combo.setVisible(selector_type == "ACCOUNT")
        for widget in (self.level_combo, self.code_from_field, self.code_to_field):
            widget.setVisible(selector_type == "RANGE")
        self.category_combo.setVisible(selector_type == "CATEGORY")
        if selector_type == "CATEGORY":
            self.level_combo.setVisible(True)

    def _describe(self, ref: AccountRefInfo) -> str:
        sign_label = "+" if ref.sign == 1 else "−"
        if ref.selector_type == "RANGE":
            level_label = _ACCOUNT_LEVEL_LABELS.get(ref.account_level, "")
            return f"{sign_label}  بازه ({level_label}): {ref.code_from} تا {ref.code_to}"
        if ref.selector_type == "CATEGORY":
            level_label = _ACCOUNT_LEVEL_LABELS.get(ref.account_level, "")
            category_label = _CATEGORY_LABELS.get(ref.category_code, ref.category_code)
            return f"{sign_label}  طبقه ({level_label}): {category_label}"
        account_label = self.account_combo.itemText(self.account_combo.findData(ref.account_id))
        return f"{sign_label}  {account_label or ref.account_id}"

    def _on_add(self) -> None:
        selector_type = self.selector_type_combo.currentData()
        sign = self.sign_combo.currentData()
        if selector_type == "ACCOUNT":
            account_id = self.account_combo.currentData()
            if account_id is None:
                return
            self._refs.append(AccountRefInfo(selector_type="ACCOUNT", sign=sign, account_id=account_id))
        elif selector_type == "RANGE":
            code_from = self.code_from_field.text().strip()
            code_to = self.code_to_field.text().strip()
            if not code_from or not code_to:
                return
            self._refs.append(
                AccountRefInfo(
                    selector_type="RANGE",
                    sign=sign,
                    account_level=self.level_combo.currentData(),
                    code_from=code_from,
                    code_to=code_to,
                )
            )
        else:  # CATEGORY
            self._refs.append(
                AccountRefInfo(
                    selector_type="CATEGORY",
                    sign=sign,
                    account_level=self.level_combo.currentData(),
                    category_code=self.category_combo.currentData(),
                )
            )
        self._refresh_list()

    def _on_remove_selected(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        del self._refs[row]
        self._refresh_list()

    def _refresh_list(self) -> None:
        self.list_widget.clear()
        for ref in self._refs:
            self.list_widget.addItem(self._describe(ref))

    def set_refs(self, refs: list[AccountRefInfo]) -> None:
        self._refs = list(refs)
        self._refresh_list()

    def refs(self) -> list[AccountRefInfo]:
        return list(self._refs)


class _RowEditorDialog(QDialog):
    def __init__(
        self,
        account_options: list[tuple[int, str]],
        other_row_options: list[tuple[int, str]],
        existing: statement_templates_service.StatementRowInfo | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("ویرایشِ ردیف" if existing else "افزودنِ ردیفِ تازه")
        self.resize(560, 620)

        layout = QVBoxLayout(self)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("نوعِ ردیف:"))
        self.row_type_combo = QComboBox()
        for code, label in _ROW_TYPE_OPTIONS:
            self.row_type_combo.addItem(label, code)
        self.row_type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self.row_type_combo, stretch=1)
        layout.addLayout(type_row)

        layout.addWidget(QLabel("برچسب:"))
        self.label_field = QLineEdit()
        layout.addWidget(self.label_field)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("تورفتگی:"))
        self.indent_spin = QSpinBox()
        self.indent_spin.setRange(0, 4)
        options_row.addWidget(self.indent_spin)
        self.bold_checkbox = QCheckBox("نمایشِ بولد (زیرکل/جمعِ کل)")
        options_row.addWidget(self.bold_checkbox)
        options_row.addStretch(1)
        layout.addLayout(options_row)

        self.accounts_label = QLabel(
            "اجزایِ حساب: حسابِ مشخص، بازه‌یِ کد یا کلِ یک طبقه (دارایی/بدهی/...) در یک سطح:"
        )
        layout.addWidget(self.accounts_label)
        self.accounts_widget = _AccountRefListWidget(account_options)
        layout.addWidget(self.accounts_widget)

        self.formula_label = QLabel("اجزایِ فرمول (جمعِ ردیف‌هایِ دیگرِ همین الگو):")
        layout.addWidget(self.formula_label)
        self.formula_widget = _RefListWidget(other_row_options)
        layout.addWidget(self.formula_widget)

        layout.addStretch(1)

        self.error_label = QLabel("")
        self.error_label.setObjectName("statusError")
        layout.addWidget(self.error_label)

        button_cluster = QWidget()
        button_cluster.setLayoutDirection(Qt.LeftToRight)
        buttons_row = QHBoxLayout(button_cluster)
        buttons_row.setContentsMargins(0, 0, 0, 0)
        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self.reject)
        buttons_row.addWidget(cancel_button)
        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._on_save_clicked)
        buttons_row.addWidget(save_button)
        layout.addWidget(button_cluster, alignment=Qt.AlignLeft)

        if existing is not None:
            index = self.row_type_combo.findData(existing.row_type)
            self.row_type_combo.setCurrentIndex(index if index >= 0 else 0)
            self.label_field.setText(existing.label)
            self.indent_spin.setValue(existing.indent_level)
            self.bold_checkbox.setChecked(existing.is_bold)
            self.accounts_widget.set_refs(existing.account_refs)
            self.formula_widget.set_refs(existing.formula_refs)

        self._on_type_changed()

    def _on_type_changed(self) -> None:
        row_type = self.row_type_combo.currentData()
        for widget in (self.accounts_label, self.accounts_widget):
            widget.setVisible(row_type == "ACCOUNTS")
        for widget in (self.formula_label, self.formula_widget):
            widget.setVisible(row_type == "FORMULA")

    def _on_save_clicked(self) -> None:
        # طبقِ بازخوردِ کاربر: قبلاً اگر برچسب خالی می‌ماند، دیالوگ بی‌سروصدا
        # بسته می‌شد و هیچ ردیفی هم ساخته نمی‌شد (جدولِ اصلی خالی می‌ماند)،
        # بدونِ هیچ پیامی — حالا پیش از بستنِ دیالوگ اعتبارسنجی می‌شود.
        if not self.label_field.text().strip():
            theme.set_status_label(self.error_label, "برچسبِ ردیف را وارد کنید.", ok=False)
            return
        row_type = self.row_type_combo.currentData()
        if row_type == "ACCOUNTS" and not self.accounts_widget.refs():
            theme.set_status_label(self.error_label, "دستِ‌کم یک حساب اضافه کنید.", ok=False)
            return
        if row_type == "FORMULA" and not self.formula_widget.refs():
            theme.set_status_label(self.error_label, "دستِ‌کم یک ردیفِ دیگر برایِ فرمول اضافه کنید.", ok=False)
            return
        self.accept()


class StatementTemplateDesignerScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._templates: list[statement_templates_service.StatementTemplateRow] = []
        self._rows: list[statement_templates_service.StatementRowInfo] = []
        self._selected_template_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_templates_panel())
        outer.addWidget(self._build_rows_panel(), stretch=1)

        # نکته: دیالوگِ ویرایشِ ردیف (_RowEditorDialog) عمداً بدونِ راهنما
        # ماند — آن دیالوگ با QDialog() بدونِ parent ساخته می‌شود (فقط با
        # exec() نمایش داده می‌شود)، پس self.parentWidget() در آن همیشه
        # None است؛ FieldHelpPanel.instance(None) بلافاصله در
        # parent.installEventFilter(self) کرش می‌کند چون None متدِ
        # installEventFilter ندارد. طبقِ راهنماییِ صریح برایِ همین حالت،
        # به‌جایِ تغییرِ نحوه‌یِ parent‌دارشدنِ دیالوگ (که خارج از محدوده‌ی
        # این کار است)، فقط همین صفحه‌ی اصلی راهنما گرفت.
        self.set_field_help([
            (
                self.new_name_field,
                "نامِ الگویِ تازه‌ای که می‌خواهید بسازید، مثلاً «صورتِ سود و زیانِ خلاصه».",
            ),
            (
                self.new_type_combo,
                "این الگو برایِ کدام نوع گزارش است. «سفارشی» یعنی هیچ‌کدام از گزارش‌هایِ استاندارد نیست.",
            ),
            (
                self.templates_list,
                "فهرستِ الگوهایِ ساخته‌شده. رویِ هرکدام کلیک کنید تا ردیف‌هایش را در سمتِ راست ببینید و ویرایش کنید.",
            ),
            (
                self.rename_field,
                "نامِ تازه برایِ الگویِ انتخاب‌شده. برایِ اعمال، دکمه‌ی «تغییرِ نام» را بزنید.",
            ),
        ])

    def _build_templates_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMaximumWidth(300)
        layout = QVBoxLayout(panel)

        title = QLabel("طراحیِ الگویِ گزارش")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.new_name_field = QLineEdit()
        self.new_name_field.setPlaceholderText("نامِ الگویِ تازه...")
        layout.addWidget(self.new_name_field)

        self.new_type_combo = QComboBox()
        for code, label in _STATEMENT_TYPE_OPTIONS:
            self.new_type_combo.addItem(label, code)
        layout.addWidget(self.new_type_combo)

        add_template_button = QPushButton("➕")
        add_template_button.setObjectName("primaryButton")
        add_template_button.setToolTip("افزودنِ الگو")
        add_template_button.clicked.connect(self._on_add_template)
        layout.addWidget(add_template_button)

        self.templates_list = QListWidget()
        self.templates_list.currentRowChanged.connect(self._on_template_selected)
        layout.addWidget(self.templates_list, stretch=1)

        rename_row = QHBoxLayout()
        self.rename_field = QLineEdit()
        rename_row.addWidget(self.rename_field, stretch=1)
        rename_button = QPushButton("✏️")
        rename_button.setObjectName("iconButton")
        rename_button.setFixedWidth(44)
        rename_button.setToolTip("تغییرِ نام")
        rename_button.clicked.connect(self._on_rename_template)
        rename_row.addWidget(rename_button)
        layout.addLayout(rename_row)

        delete_template_button = QPushButton("🗑️")
        delete_template_button.setObjectName("dangerIconButton")
        delete_template_button.setFixedWidth(44)
        delete_template_button.setToolTip("حذفِ الگو")
        delete_template_button.clicked.connect(self._on_delete_template)
        layout.addWidget(delete_template_button)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        return wrap_scrollable(panel)

    def _build_rows_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.rows_title = QLabel("ردیف‌هایِ الگو")
        self.rows_title.setObjectName("sectionHint")
        layout.addWidget(self.rows_title)

        self.rows_table = QTableWidget(0, len(_ROW_COLUMNS))
        self.rows_table.setHorizontalHeaderLabels(_ROW_COLUMNS)
        self.rows_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rows_table.verticalHeader().setVisible(False)
        # طبقِ همان بازخوردی که در journal_entry.py/financial_statement_mapping.py
        # رفع شد: ارتفاعِ پیش‌فرضِ ردیف برایِ چهار دکمه‌یِ کنارِ‌هم (▲▼ ویرایش
        # حذف) کافی نبود — دکمه‌ها بریده/نامرئی دیده می‌شدند.
        self.rows_table.verticalHeader().setDefaultSectionSize(44)
        header = self.rows_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.rows_table.setColumnWidth(4, 232)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        layout.addWidget(self.rows_table, stretch=1)

        add_row_button = QPushButton("➕")
        add_row_button.setObjectName("primaryButton")
        add_row_button.setToolTip("افزودنِ ردیف")
        add_row_button.clicked.connect(self._on_add_row)
        layout.addWidget(add_row_button)

        return wrap_scrollable(panel)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        theme.set_status_label(self.status_label, "", ok=True)
        company_id = self._company_id()
        self._templates = (
            statement_templates_service.list_templates(company_id) if company_id is not None else []
        )
        self.templates_list.blockSignals(True)
        self.templates_list.clear()
        for t in self._templates:
            self.templates_list.addItem(f"{t.name} ({_STATEMENT_TYPE_LABELS.get(t.statement_type, t.statement_type)})")
        self.templates_list.blockSignals(False)
        if self._templates:
            self.templates_list.setCurrentRow(0)
            self._on_template_selected(0)
        else:
            self._selected_template_id = None
            self.rename_field.setText("")
            self._reload_rows()

    def _on_template_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._templates):
            self._selected_template_id = None
            self.rename_field.setText("")
        else:
            self._selected_template_id = self._templates[row].template_id
            self.rename_field.setText(self._templates[row].name)
        self._reload_rows()

    def _reload_rows(self) -> None:
        self._rows = (
            statement_templates_service.list_rows(self._selected_template_id)
            if self._selected_template_id is not None
            else []
        )
        self.rows_table.setRowCount(len(self._rows))
        for row_index, row_info in enumerate(self._rows):
            self.rows_table.setItem(
                row_index, 0, QTableWidgetItem(_ROW_TYPE_LABELS.get(row_info.row_type, row_info.row_type))
            )
            self.rows_table.setItem(row_index, 1, QTableWidgetItem(row_info.label))
            self.rows_table.setItem(row_index, 2, QTableWidgetItem(str(row_info.indent_level)))
            self.rows_table.setItem(row_index, 3, QTableWidgetItem("بله" if row_info.is_bold else ""))
            self.rows_table.setCellWidget(row_index, 4, self._build_row_actions(row_index, row_info))

    def _build_row_actions(self, row_index: int, row_info: statement_templates_service.StatementRowInfo) -> QWidget:
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(2, 0, 2, 0)

        # طبقِ کشفِ عیب: پدینگِ سراسریِ QPushButton (۱۶px از هرطرف) بیشتر از
        # عرضِ ثابتِ ۲۸px بود، پس گلیفِ ▲/▼ اصلاً جایی برایِ رسم‌شدن نداشت و
        # دکمه‌ها کاملاً نامرئی می‌شدند — این‌جا پدینگِ فشرده‌تری override
        # می‌شود، مخصوصِ همین دو دکمه‌یِ کوچکِ آیکونی.
        up_button = QPushButton("▲")
        up_button.setFixedWidth(28)
        up_button.setStyleSheet("padding: 2px;")
        up_button.setToolTip("جابه‌جایی به بالا")
        up_button.clicked.connect(lambda _checked=False, i=row_index: self._on_move_row(i, -1))
        cell_layout.addWidget(up_button)

        down_button = QPushButton("▼")
        down_button.setFixedWidth(28)
        down_button.setStyleSheet("padding: 2px;")
        down_button.setToolTip("جابه‌جایی به پایین")
        down_button.clicked.connect(lambda _checked=False, i=row_index: self._on_move_row(i, 1))
        cell_layout.addWidget(down_button)

        edit_button = QPushButton("✏️")
        edit_button.setObjectName("iconButton")
        edit_button.setFixedWidth(44)
        edit_button.setToolTip("ویرایش")
        edit_button.clicked.connect(lambda _checked=False, r=row_info: self._on_edit_row(r))
        cell_layout.addWidget(edit_button)

        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(44)
        delete_button.setToolTip("حذف")
        delete_button.clicked.connect(lambda _checked=False, r=row_info: self._on_delete_row(r))
        cell_layout.addWidget(delete_button)

        return cell

    def _on_add_template(self) -> None:
        company_id = self._company_id()
        name = self.new_name_field.text().strip()
        if company_id is None or not name:
            return
        statement_templates_service.create_template(company_id, name, self.new_type_combo.currentData())
        self.new_name_field.clear()
        self.refresh()

    def _on_rename_template(self) -> None:
        if self._selected_template_id is None:
            return
        name = self.rename_field.text().strip()
        if not name:
            return
        statement_templates_service.rename_template(self._selected_template_id, name)
        self.refresh()

    def _on_delete_template(self) -> None:
        if self._selected_template_id is None:
            return
        statement_templates_service.delete_template(self._selected_template_id)
        self.refresh()

    def _account_options(self) -> list[tuple[int, str]]:
        company_id = self._company_id()
        if company_id is None:
            return []
        return [(a.account_id, f"{a.full_code} — {a.name}") for a in coa_service.list_accounts(company_id)]

    def _other_row_options(self, exclude_row_id: int | None = None) -> list[tuple[int, str]]:
        return [(r.row_id, r.label) for r in self._rows if r.row_id != exclude_row_id]

    def _on_add_row(self) -> None:
        if self._selected_template_id is None:
            theme.set_status_label(self.status_label, "ابتدا یک الگو انتخاب/بسازید.", ok=False)
            return
        dialog = _RowEditorDialog(self._account_options(), self._other_row_options())
        if dialog.exec() != QDialog.Accepted:
            return
        label = dialog.label_field.text().strip()
        if not label:
            return
        row_type = dialog.row_type_combo.currentData()
        row_id = statement_templates_service.add_row(
            self._selected_template_id,
            label,
            row_type,
            indent_level=dialog.indent_spin.value(),
            is_bold=dialog.bold_checkbox.isChecked(),
        )
        if row_type == "ACCOUNTS":
            statement_templates_service.set_row_accounts(row_id, dialog.accounts_widget.refs())
        elif row_type == "FORMULA":
            statement_templates_service.set_row_formula_refs(row_id, dialog.formula_widget.refs())
        self._reload_rows()

    def _on_edit_row(self, row_info: statement_templates_service.StatementRowInfo) -> None:
        dialog = _RowEditorDialog(
            self._account_options(), self._other_row_options(exclude_row_id=row_info.row_id), existing=row_info
        )
        if dialog.exec() != QDialog.Accepted:
            return
        label = dialog.label_field.text().strip()
        if not label:
            return
        row_type = dialog.row_type_combo.currentData()
        statement_templates_service.update_row(
            row_info.row_id,
            label=label,
            row_type=row_type,
            indent_level=dialog.indent_spin.value(),
            is_bold=dialog.bold_checkbox.isChecked(),
        )
        statement_templates_service.set_row_accounts(
            row_info.row_id, dialog.accounts_widget.refs() if row_type == "ACCOUNTS" else []
        )
        statement_templates_service.set_row_formula_refs(
            row_info.row_id, dialog.formula_widget.refs() if row_type == "FORMULA" else []
        )
        self._reload_rows()

    def _on_delete_row(self, row_info: statement_templates_service.StatementRowInfo) -> None:
        statement_templates_service.delete_row(row_info.row_id)
        self._reload_rows()

    def _on_move_row(self, row_index: int, direction: int) -> None:
        new_index = row_index + direction
        if new_index < 0 or new_index >= len(self._rows):
            return
        ids = [r.row_id for r in self._rows]
        ids[row_index], ids[new_index] = ids[new_index], ids[row_index]
        statement_templates_service.reorder_rows(self._selected_template_id, ids)
        self._reload_rows()
