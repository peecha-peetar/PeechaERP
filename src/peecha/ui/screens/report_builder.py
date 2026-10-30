"""R374: گزارش‌ساز آزاد — انتخاب داده، ستون‌ها، فیلتر، گروه‌بندی و جمع، مرتب‌سازی، اجرا، ذخیره، خروجی اکسل و چاپ."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox,
    QSplitter, QStackedWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import decimals, numerals
from peecha.services.report_builder import engine
from peecha.services.report_builder.datasets import DATE, DATASETS, INT, MONEY, NUMERIC, QTY
from peecha.ui import report_export, theme
from peecha.ui.screens.fixed_assets import P, company_id, fill, selected_data, set_combo, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def show_value(value, kind: str) -> str:
    """متن نمایشی هر خانهٔ نتیجه (برای جدول و چاپ)."""
    if value is None or value == "":
        return ""
    if isinstance(value, datetime.date):
        return numerals.format_jalali_date(value)
    if kind == MONEY:
        return decimals.format_amount(value)
    if kind in (QTY, INT):
        return P(f"{decimal.Decimal(value).normalize():f}") if isinstance(value, decimal.Decimal) else P(value)
    return P(value)


def excel_value(value):
    if isinstance(value, datetime.date):
        return numerals.format_jalali_date(value)
    return value


class ReportBuilderScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.reports: list[engine.SavedReport] = []
        self.report_id: int | None = None
        self.filters: list[engine.Filter] = []
        self.result: engine.Result | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "گزارش‌ساز", "داده را انتخاب کنید، ستون‌ها و فیلترها را بچینید، در صورت نیاز گروه‌بندی و جمع بگیرید و گزارش را برای خودتان "
            "یا همکاران ذخیره کنید. فقط داده‌هایی نمایش داده می‌شود که به فرم‌های آن دسترسی دارید."))
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_saved())
        from peecha.ui.screens.report_schedules import ReportSchedulePanel  # R375

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_editor(), "طراحی و نتیجه")
        self.schedule_panel = ReportSchedulePanel(self._status)
        self.tabs.addTab(self.schedule_panel, "زمان‌بندی و ارسال")
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 4)
        layout.addWidget(splitter, 1)

    # --- ساخت -----------------------------------------------------------------------------------------------
    def _build_saved(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel("گزارش‌های ذخیره‌شده"))
        self.saved_table = table(["نام", "داده", "اشتراکی"])
        self.saved_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.saved_table.itemSelectionChanged.connect(self._open_selected)
        v.addWidget(self.saved_table, 1)
        row = QHBoxLayout()
        for label, glyph, kind, slot in (("گزارش جدید", "🆕", "", self.new_report), ("حذف گزارش", "🗑️", "danger", self.delete_report)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        v.addLayout(row)
        return page

    def _build_editor(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        self.name_field = QLineEdit()
        self.dataset_combo = QComboBox()
        self.dataset_combo.currentIndexChanged.connect(self._dataset_changed)
        self.shared_box = QCheckBox("نمایش برای همکاران")
        v.addWidget(FieldGrid([FieldSpec("rb_name", "نام گزارش", self.name_field, span=2),
                               FieldSpec("rb_dataset", "داده", self.dataset_combo, span=2),
                               FieldSpec("rb_shared", "اشتراک", self.shared_box, span=1)]))
        self.dataset_hint = QLabel("")
        self.dataset_hint.setWordWrap(True)
        v.addWidget(self.dataset_hint)
        mid = QHBoxLayout()
        col_box = QVBoxLayout()
        col_box.addWidget(QLabel("ستون‌ها (تیک بزنید؛ ترتیب با جابه‌جایی)"))
        self.column_list = QListWidget()
        self.column_list.setMaximumHeight(170)
        self.column_list.itemChanged.connect(lambda _i: self._columns_changed())
        col_box.addWidget(self.column_list)
        move = QHBoxLayout()
        for label, glyph, slot in (("بالا بردن ستون", "⬆️", lambda: self._move(-1)), ("پایین بردن ستون", "⬇️", lambda: self._move(1))):
            button = _btn(label, glyph)
            button.clicked.connect(slot)
            move.addWidget(button)
        move.addStretch(1)
        col_box.addLayout(move)
        mid.addLayout(col_box, 1)
        filter_box = QVBoxLayout()
        filter_box.addWidget(QLabel("فیلترها"))
        self.filter_column = QComboBox()
        self.filter_column.currentIndexChanged.connect(self._filter_column_changed)
        self.filter_op = QComboBox()
        self.value_stack, self.value2_stack = QStackedWidget(), QStackedWidget()
        self.value_text, self.value2_text = QLineEdit(), QLineEdit()
        self.value_date, self.value2_date = JalaliDateEdit(), JalaliDateEdit()
        self.value_stack.addWidget(self.value_text)
        self.value_stack.addWidget(self.value_date)
        self.value2_stack.addWidget(self.value2_text)
        self.value2_stack.addWidget(self.value2_date)
        frow = QHBoxLayout()
        frow.addWidget(FieldGrid([FieldSpec("rb_fcol", "ستون", self.filter_column, span=1), FieldSpec("rb_fop", "شرط", self.filter_op, span=1),
                                  FieldSpec("rb_fval", "مقدار", self.value_stack, span=1),
                                  FieldSpec("rb_fval2", "مقدار دوم (بین)", self.value2_stack, span=1)]), 1)
        for label, glyph, kind, slot in (("افزودن فیلتر", "➕", "", self.add_filter), ("برداشتن فیلتر انتخاب‌شده", "➖", "danger", self.remove_filter)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            frow.addWidget(button)
        filter_box.addLayout(frow)
        self.filter_table = table(["ستون", "شرط"])
        self.filter_table.setMaximumHeight(110)
        filter_box.addWidget(self.filter_table)
        mid.addLayout(filter_box, 2)
        v.addLayout(mid)
        self.group_box = QCheckBox("گروه‌بندی و جمع")
        self.count_box = QCheckBox("ستون تعداد ردیف")
        self.date_group = QComboBox()
        for code, label in engine.DATE_GROUPS.items():
            self.date_group.addItem(label, code)
        self.agg_column, self.agg_kind = QComboBox(), QComboBox()
        for code, label in engine.AGGREGATES.items():
            self.agg_kind.addItem(label, code)
        self.agg_kind.currentIndexChanged.connect(self._set_aggregate)
        self.agg_column.currentIndexChanged.connect(self._show_aggregate)
        self.sort_combo = QComboBox()
        self.sort_desc = QCheckBox("نزولی")
        self.limit_field = QSpinBox()
        self.limit_field.setRange(0, engine.MAX_ROWS)
        self.limit_field.setSpecialValueText("همه")
        v.addWidget(FieldGrid([
            FieldSpec("rb_group", "گروه‌بندی", self.group_box, span=1), FieldSpec("rb_dgroup", "تاریخ به تفکیک", self.date_group, span=1),
            FieldSpec("rb_count", "تعداد", self.count_box, span=1), FieldSpec("rb_aggcol", "ستون عددی", self.agg_column, span=1),
            FieldSpec("rb_agg", "نوع جمع", self.agg_kind, span=1), FieldSpec("rb_sort", "مرتب‌سازی بر اساس", self.sort_combo, span=1),
            FieldSpec("rb_desc", "ترتیب", self.sort_desc, span=1), FieldSpec("rb_limit", "سقف ردیف", self.limit_field, span=1)]))
        bar = QHBoxLayout()
        for label, glyph, kind, slot in (("اجرای گزارش", "▶️", "primary", self.run), ("ذخیرهٔ گزارش", "💾", "", self.save_report),
                                         ("خروجی Excel", "📊", "", self.export_excel), ("چاپ", "🖨️", "", self.print_result)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        v.addLayout(bar)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        v.addWidget(self.summary_label)
        self.result_table = table([])
        v.addWidget(self.result_table, 1)
        self.aggregates: dict[str, str] = {}
        return page

    # --- داده و ستون‌ها -----------------------------------------------------------------------------------------
    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    def refresh(self) -> None:
        cid, uid = company_id(), user_id()
        if cid is None or uid is None:
            return
        current = self.dataset_combo.currentData()
        self.dataset_combo.blockSignals(True)
        self.dataset_combo.clear()
        for d in engine.available(cid, uid):
            self.dataset_combo.addItem(d.label, d.code)
        self.dataset_combo.blockSignals(False)
        if current:
            set_combo(self.dataset_combo, current)
        self._dataset_changed()
        self._load_saved()
        self.schedule_panel.set_report(self.report_id)

    def _load_saved(self) -> None:
        self.reports = engine.list_reports(company_id(), user_id())
        fill(self.saved_table, [[r.name, r.dataset_label, "بله" if r.is_shared else ""] for r in self.reports],
             [r.report_id for r in self.reports])
        row = next((i for i, r in enumerate(self.reports) if r.report_id == self.report_id), None)
        if row is not None:
            self.saved_table.blockSignals(True)
            self.saved_table.setCurrentCell(row, 0)
            self.saved_table.blockSignals(False)

    def _dataset(self):
        return DATASETS.get(self.dataset_combo.currentData())

    def _dataset_changed(self, checked: list[str] | None = None) -> None:
        d = self._dataset()
        self.column_list.blockSignals(True)
        self.column_list.clear()
        self.filter_column.blockSignals(True)
        self.filter_column.clear()
        if d is not None:
            self.dataset_hint.setText(d.description)
            order = list(checked or [])
            columns = [d.column(k) for k in order if d.column(k)] + [c for c in d.columns if c.key not in order]
            for c in columns:
                item = QListWidgetItem(c.label)
                item.setData(Qt.UserRole, c.key)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if (c.key in order if checked is not None else True) else Qt.Unchecked)
                self.column_list.addItem(item)
            for c in d.columns:
                self.filter_column.addItem(c.label, c.key)
        self.column_list.blockSignals(False)
        self.filter_column.blockSignals(False)
        if checked is None:
            self.filters, self.aggregates = [], {}
            self._show_filters()
        self._filter_column_changed()
        self._columns_changed()

    def selected_columns(self) -> list[str]:
        return [self.column_list.item(i).data(Qt.UserRole) for i in range(self.column_list.count())
                if self.column_list.item(i).checkState() == Qt.Checked]

    def _columns_changed(self) -> None:
        d = self._dataset()
        keys = self.selected_columns()
        sort = self.sort_combo.currentData()
        self.sort_combo.clear()
        self.sort_combo.addItem("بدون مرتب‌سازی", None)
        self.agg_column.blockSignals(True)
        self.agg_column.clear()
        for k in keys:
            c = d.column(k)
            self.sort_combo.addItem(c.label, k)
            if c.kind in NUMERIC:
                self.agg_column.addItem(c.label, k)
        self.agg_column.blockSignals(False)
        self.sort_combo.addItem("تعداد ردیف", engine.COUNT_KEY)
        set_combo(self.sort_combo, sort)
        self._show_aggregate()

    def _move(self, step: int) -> None:
        row = self.column_list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.column_list.count():
            return
        item = self.column_list.takeItem(row)
        self.column_list.insertItem(target, item)
        self.column_list.setCurrentRow(target)
        self._columns_changed()

    def _show_aggregate(self) -> None:
        key = self.agg_column.currentData()
        self.agg_kind.blockSignals(True)
        set_combo(self.agg_kind, self.aggregates.get(key, "SUM"))
        self.agg_kind.blockSignals(False)

    def _set_aggregate(self) -> None:
        key = self.agg_column.currentData()
        if key:
            self.aggregates[key] = self.agg_kind.currentData()

    # --- فیلترها --------------------------------------------------------------------------------------------
    def _filter_column_changed(self) -> None:
        d = self._dataset()
        c = d.column(self.filter_column.currentData()) if d else None
        self.filter_op.clear()
        if c is None:
            return
        for code, label in engine.ops_for(c.kind).items():
            self.filter_op.addItem(label, code)
        is_date = c.kind == DATE
        self.value_stack.setCurrentIndex(1 if is_date else 0)
        self.value2_stack.setCurrentIndex(1 if is_date else 0)

    def add_filter(self) -> bool:
        d = self._dataset()
        c = d.column(self.filter_column.currentData()) if d else None
        if c is None:
            return False
        op = self.filter_op.currentData()
        if c.kind == DATE:
            value, value2 = self.value_date.date(), self.value2_date.date()
        else:
            value, value2 = self.value_text.text().strip(), self.value2_text.text().strip()
        f = engine.Filter(c.key, op, value, value2 if op == "BETWEEN" else None)
        try:
            engine.validate(engine.Definition(d.code, [d.columns[0].key], [f]))
            if c.kind in NUMERIC and op not in ("EMPTY", "NOT_EMPTY"):
                engine.parse_number(value)
                if op == "BETWEEN":
                    engine.parse_number(value2)
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "مقدار فیلتر عددی نیست.", False)
            return False
        self.filters.append(f)
        self.value_text.clear()
        self.value2_text.clear()
        self._show_filters()
        return True

    def remove_filter(self) -> None:
        index = selected_data(self.filter_table)
        if index is not None:
            del self.filters[index]
            self._show_filters()

    def _show_filters(self) -> None:
        d = self._dataset()
        rows = engine.filters_text(d, self.filters) if d else []
        fill(self.filter_table, [[label, text] for label, text in rows], list(range(len(rows))))

    # --- تعریف، اجرا و ذخیره ------------------------------------------------------------------------------------
    def definition(self) -> engine.Definition:
        d = self._dataset()
        keys = self.selected_columns()
        return engine.Definition(d.code if d else "", keys, list(self.filters), self.group_box.isChecked(),
                                 self.date_group.currentData(), {k: v for k, v in self.aggregates.items() if k in keys},
                                 self.count_box.isChecked(), self.sort_combo.currentData(), self.sort_desc.isChecked(),
                                 self.limit_field.value() or None)

    def run(self) -> bool:
        if company_id() is None or self._dataset() is None:
            self._status("داده‌ای برای گزارش در دسترس نیست.", False)
            return False
        try:
            r = self.result = engine.run(company_id(), user_id(), self.definition(), self.name_field.text().strip())
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.result_table.clear()
        self.result_table.setColumnCount(len(r.headers))
        self.result_table.setHorizontalHeaderLabels(r.headers)
        rows = r.rows + ([r.totals] if r.totals else [])
        self.result_table.setRowCount(len(rows))
        for i, line in enumerate(rows):
            for j, value in enumerate(line):
                text = show_value(value, r.kinds[j])
                if i == len(r.rows) and j == 0 and not text:
                    text = "جمع"
                item = QTableWidgetItem(text)
                if r.kinds[j] in NUMERIC:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.result_table.setItem(i, j, item)
        note = f"{P(len(r.rows))} ردیف" + (f" (از {P(r.row_count_before_limit)})" if r.row_count_before_limit > len(r.rows) else "")
        if r.truncated:
            note += f" | فقط {P(engine.MAX_ROWS)} ردیف اول داده خوانده شد؛ بازهٔ تاریخ را کوتاه‌تر کنید"
        self.summary_label.setText(f"{note} | منبع: {r.source}")
        self._status("گزارش اجرا شد.", True)
        return True

    def save_report(self) -> int | None:
        try:
            self.report_id = engine.save_report(company_id(), user_id(), self.name_field.text(), self.definition(),
                                                self.shared_box.isChecked(), self.report_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self._load_saved()
        self.schedule_panel.set_report(self.report_id)
        self._status("گزارش ذخیره شد.", True)
        return self.report_id

    def _open_selected(self) -> None:
        rid = selected_data(self.saved_table)
        r = next((x for x in self.reports if x.report_id == rid), None)
        if r is not None:
            self.open_report(r)

    def open_report(self, r: engine.SavedReport) -> None:
        self.report_id = r.report_id
        self.name_field.setText(r.name)
        self.shared_box.setChecked(r.is_shared)
        self.dataset_combo.blockSignals(True)
        set_combo(self.dataset_combo, r.dataset_code)
        self.dataset_combo.blockSignals(False)
        definition = r.definition
        self.filters, self.aggregates = list(definition.filters), dict(definition.aggregates)
        self._dataset_changed(definition.columns)
        self._show_filters()
        self.group_box.setChecked(definition.group)
        set_combo(self.date_group, definition.date_group)
        self.count_box.setChecked(definition.count_rows)
        set_combo(self.sort_combo, definition.sort_key)
        self.sort_desc.setChecked(definition.sort_desc)
        self.limit_field.setValue(int(definition.limit or 0))
        self._show_aggregate()
        self.schedule_panel.set_report(r.report_id)

    def load_definition(self, definition: engine.Definition, name: str = "") -> bool:
        """R376: طرح ساخته‌شده در دستیار، به‌صورت گزارش جدید (ذخیره‌نشده) و اجراشده."""
        self.new_report()
        self.name_field.setText(name[:150])
        self.dataset_combo.blockSignals(True)
        set_combo(self.dataset_combo, definition.dataset)
        self.dataset_combo.blockSignals(False)
        self.filters, self.aggregates = list(definition.filters), dict(definition.aggregates)
        self._dataset_changed(definition.columns)
        self._show_filters()
        self.group_box.setChecked(definition.group)
        set_combo(self.date_group, definition.date_group)
        self.count_box.setChecked(definition.count_rows)
        set_combo(self.sort_combo, definition.sort_key)
        self.sort_desc.setChecked(definition.sort_desc)
        self.limit_field.setValue(int(definition.limit or 0))
        self._show_aggregate()
        return self.run()

    def new_report(self) -> None:
        self.report_id = None
        self.saved_table.clearSelection()
        self.name_field.clear()
        self.shared_box.setChecked(False)
        self.group_box.setChecked(False)
        self.count_box.setChecked(False)
        self.sort_desc.setChecked(False)
        self.limit_field.setValue(0)
        self._dataset_changed()
        self.schedule_panel.set_report(None)

    def delete_report(self) -> bool:
        if self.report_id is None:
            self._status("یک گزارش ذخیره‌شده را انتخاب کنید.", False)
            return False
        try:
            engine.delete_report(company_id(), user_id(), self.report_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.new_report()
        self._load_saved()
        self._status("گزارش حذف شد.", True)
        return True

    # --- خروجی --------------------------------------------------------------------------------------------
    def _printable(self):
        r = self.result
        rows = [[show_value(v, r.kinds[j]) for j, v in enumerate(line)] for line in r.rows]
        footer = [show_value(v, r.kinds[j]) if v is not None else ("جمع" if j == 0 else "") for j, v in enumerate(r.totals)] if r.totals else None
        return rows, footer

    def export_excel(self) -> bool:
        if self.result is None or not self.result.rows:
            self._status("اول گزارش را اجرا کنید.", False)
            return False
        r = self.result
        footer = [excel_value(v) for v in r.totals] if r.totals else None
        report_export.export_report_excel(self, r.title, r.headers, [[excel_value(v) for v in line] for line in r.rows], footer,
                                          filters=r.filters_text)
        return True

    def print_result(self) -> bool:
        if self.result is None or not self.result.rows:
            self._status("اول گزارش را اجرا کنید.", False)
            return False
        rows, footer = self._printable()
        report_export.print_report(self, self.result.title, self.result.headers, rows, footer, filters=self.result.filters_text)
        return True
