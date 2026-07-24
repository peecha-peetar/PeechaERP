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
from peecha.ui import theme

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

        add_button = QPushButton("افزودن")
        add_button.setObjectName("flatButton")
        add_button.clicked.connect(self._on_add)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        self.list_widget = QListWidget()
        self.list_widget.setMaximumHeight(110)
        layout.addWidget(self.list_widget)

        remove_button = QPushButton("حذفِ موردِ انتخاب‌شده")
        remove_button.setObjectName("flatButton")
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


class _RowEditorDialog(QDialog):
    def __init__(
        self,
        account_options: list[tuple[int, str]],
        other_row_options: list[tuple[int, str]],
        existing: statement_templates_service.StatementRowInfo | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("ویرایشِ ردیف" if existing else "افزودنِ ردیفِ تازه")
        self.resize(520, 480)

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

        self.accounts_label = QLabel("اجزایِ حساب (هر سطحی: گروه/کل/معین):")
        layout.addWidget(self.accounts_label)
        self.accounts_widget = _RefListWidget(account_options)
        layout.addWidget(self.accounts_widget)

        self.formula_label = QLabel("اجزایِ فرمول (جمعِ ردیف‌هایِ دیگرِ همین الگو):")
        layout.addWidget(self.formula_label)
        self.formula_widget = _RefListWidget(other_row_options)
        layout.addWidget(self.formula_widget)

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


class StatementTemplateDesignerScreen(QWidget):
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

        add_template_button = QPushButton("افزودنِ الگو")
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

        delete_template_button = QPushButton("حذفِ الگو")
        delete_template_button.setObjectName("dangerButton")
        delete_template_button.clicked.connect(self._on_delete_template)
        layout.addWidget(delete_template_button)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        return panel

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
        self.rows_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.rows_table, stretch=1)

        add_row_button = QPushButton("افزودنِ ردیف")
        add_row_button.setObjectName("primaryButton")
        add_row_button.clicked.connect(self._on_add_row)
        layout.addWidget(add_row_button)

        return panel

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

        up_button = QPushButton("▲")
        up_button.setFixedWidth(28)
        up_button.clicked.connect(lambda _checked=False, i=row_index: self._on_move_row(i, -1))
        cell_layout.addWidget(up_button)

        down_button = QPushButton("▼")
        down_button.setFixedWidth(28)
        down_button.clicked.connect(lambda _checked=False, i=row_index: self._on_move_row(i, 1))
        cell_layout.addWidget(down_button)

        edit_button = QPushButton("ویرایش")
        edit_button.setObjectName("flatButton")
        edit_button.clicked.connect(lambda _checked=False, r=row_info: self._on_edit_row(r))
        cell_layout.addWidget(edit_button)

        delete_button = QPushButton("حذف")
        delete_button.setObjectName("dangerButton")
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
