"""فهرستِ واحدِ همه‌ی تفصیلی‌ها — معادلِ Qt برایِ detail_accounts_list.py/.kv
در Kivy. کلیک روی هر ردیف بسته به نوعِ گروهش، صفحه‌ی درست را باز می‌کند.

طبقِ بازخوردِ صریح: این فهرست حالا یک نمایِ درختی است — هر گروهِ تفصیلی
(کالا/بانک/صندوق/... و مشتری/تامین‌کننده/پرسنل/گروه‌هایِ ساده) یک گرهِ
سرگروه دارد که با رنگِ اختصاصیِ همان گروه (اگر تنظیم شده) رنگ‌آمیزی
می‌شود؛ به‌طورِ پیش‌فرض فقط برگ‌ها (پایین‌ترین سطحِ هر گروه) زیرِ همان
گره نشان داده می‌شوند — چون در سلسله‌مراتبِ چندسطحی معمولاً فقط برگ‌ها
در عمل قابل‌انتخاب‌اند؛ چک‌باکسِ «نمایشِ همه‌یِ سطوح» کاربر را به سلسله‌مراتبِ
کاملِ والد/فرزند سوییچ می‌دهد."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import datetime

from peecha import numerals, session
from peecha.services import detail_dimensions as dimensions_service
from peecha.ui import report_export
from peecha.ui.widgets import FieldHelpMixin

# طبقِ درخواستِ صریح («کد باید اولین ستون از سمتِ راست باشد، در همه‌ی
# فرم‌هایِ این‌شکلی») — هم‌الگو با ترتیبِ ستون‌هایِ کدینگِ حساب‌ها؛ چونی که
# QTreeWidget زیرِ RTL هم مثلِ QTableWidget، ستونِ اندیسِ ۰ در لبه‌یِ
# فیزیکیِ راست ظاهر می‌شود، پس «کد» باید ستونِ اول باشد نه «نام».
_COLUMNS = ["کد", "نام", "سطح", "وضعیت"]


def _group_label(group_name: str) -> str:
    """گروه‌هایِ اشخاص از قبل با نامِ فارسی (مثلِ «مشتری») ذخیره شده‌اند؛
    گروه‌هایِ عمومی با کدِ خام (مثلِ «CASH_BOX») که این‌جا به برچسبِ فارسی
    ترجمه می‌شود — کدِ خام برایِ مسیریابی دست‌نخورده می‌ماند."""
    return dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(group_name, group_name)


class DetailAccountsListScreen(FieldHelpMixin, QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._entries: list[dimensions_service.UnifiedDetailAccountRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header_row = QHBoxLayout()
        title = QLabel("تفصیلی‌ها")
        title.setObjectName("pageTitle")
        header_row.addWidget(title)
        header_row.addStretch(1)

        # طبقِ درخواستِ صریح: دکمه‌ی «تفصیلیِ جدید» با منویی از همه‌ی
        # گروه‌هایِ تفصیلی — با انتخابِ هرکدام، همان فرمِ اختصاصی‌اش در
        # حالتِ «رکوردِ تازه» باز می‌شود (نه لیستِ خودِ گروه‌ها).
        self.new_entry_button = QPushButton("➕")
        self.new_entry_button.setObjectName("primaryIconButton")
        self.new_entry_button.setFixedWidth(40)
        self.new_entry_button.setToolTip("تفصیلیِ جدید")
        self.new_entry_button.clicked.connect(self._show_new_entry_menu)
        header_row.addWidget(self.new_entry_button)

        # طبقِ درخواستِ صریح («خروجیِ اکسل و چاپی از تفصیلی‌ها، برایِ
        # برگرداندن روی دیتابیسِ جدید»): خروجیِ اکسل خام است (فقط عنوان+
        # دیتا) تا قابلِ‌ایمپورتِ مجدد باشد؛ چاپ/PDF با هدرِ کاملِ گزارش.
        print_button = QPushButton("🖨 چاپ")
        print_button.setObjectName("flatButton")
        print_button.clicked.connect(self._on_print)
        header_row.addWidget(print_button)
        pdf_button = QPushButton("📄 PDF")
        pdf_button.setObjectName("flatButton")
        pdf_button.clicked.connect(self._on_export_pdf)
        header_row.addWidget(pdf_button)
        excel_button = QPushButton("📊 خروجیِ اکسل")
        excel_button.setObjectName("flatButton")
        excel_button.clicked.connect(self._on_export_excel)
        header_row.addWidget(excel_button)
        layout.addLayout(header_row)

        hint = QLabel(
            "همه‌ی مشتریان/تامین‌کنندگان/پرسنل/مراکزِ هزینه/پروژه‌ها و گروه‌های دیگرِ تفصیلی، یک‌جا — "
            "کلیک روی هر ردیف فرمِ مربوطه را باز می‌کند."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        filter_row = QHBoxLayout()
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("جستجو در نوعِ تفصیلی، کد یا نام")
        self.search_field.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.search_field, stretch=1)

        # طبقِ درخواستِ صریح: به‌طورِ پیش‌فرض فقط سطوحِ آخر (برگ‌ها) نمایش
        # داده می‌شوند؛ با این چک‌باکس می‌توان کلِ سلسله‌مراتب را دید.
        self.show_all_levels_checkbox = QCheckBox("نمایشِ همه‌یِ سطوح")
        self.show_all_levels_checkbox.toggled.connect(self._apply_filter)
        filter_row.addWidget(self.show_all_levels_checkbox)
        layout.addLayout(filter_row)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(_COLUMNS))
        self.tree.setHeaderLabels(_COLUMNS)
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree, stretch=1)

        self.set_field_help([
            (
                self.search_field,
                "جستجو در نوعِ گروه، کد یا نام، رویِ همه‌یِ تفصیلی‌ها با هم — کالا، بانک، مشتری و بقیه.",
            ),
            (
                self.show_all_levels_checkbox,
                "به‌طورِ پیش‌فرض فقط آخرین سطح (برگ‌ها) نشان داده می‌شود. با این تیک، کلِ درختِ والد و فرزندِ هر گروه را می‌بینید.",
            ),
        ])

    def refresh(self) -> None:
        company_id = session.current_company.company_id if session.current_company else None
        self._entries = dimensions_service.list_all_detail_accounts(company_id) if company_id is not None else []
        self._apply_filter()

    # --- خروجیِ اکسل/چاپ (طبقِ درخواستِ صریح: بکاپ/انتقالِ تفصیلی‌ها به
    # دیتابیسِ جدید) ------------------------------------------------------
    _EXPORT_HEADERS = ["کدِ کاملِ حساب", "کد", "نام", "سطح", "وضعیت", "گروهِ تفصیلی", "کدِ کاملِ والد"]

    def _export_rows(self) -> tuple[list[str], list[list], list]:
        full_code_by_id = {e.detail_account_id: e.full_code for e in self._entries}
        table_rows = [
            [
                e.full_code,
                e.code,
                e.name or "—",
                e.level_no,
                "فعال" if e.is_active else "غیرفعال",
                _group_label(e.group_name),
                full_code_by_id.get(e.parent_detail_account_id, "") if e.parent_detail_account_id else "",
            ]
            for e in sorted(self._entries, key=lambda r: (_group_label(r.group_name), r.full_code))
        ]
        return list(self._EXPORT_HEADERS), table_rows, []

    def _export_kwargs(self) -> dict:
        return {
            "company_name": session.current_company.display_name if session.current_company else "",
            "report_date": numerals.format_jalali_date(datetime.date.today()),
        }

    def _on_print(self) -> None:
        headers, rows, footer = self._export_rows()
        report_export.print_report(self, "تفصیلی‌ها", headers, rows, footer, **self._export_kwargs())

    def _on_export_pdf(self) -> None:
        headers, rows, footer = self._export_rows()
        report_export.export_report_pdf(self, "تفصیلی‌ها", headers, rows, footer, **self._export_kwargs())

    def _on_export_excel(self) -> None:
        _headers, rows, _footer = self._export_rows()
        report_export.export_plain_excel(self, "تفصیلی‌ها", self._EXPORT_HEADERS, rows)

    def _matches_query(self, e: dimensions_service.UnifiedDetailAccountRow, query: str) -> bool:
        if not query:
            return True
        return query in _group_label(e.group_name) or query in e.full_code or bool(e.name and query in e.name)

    def _apply_filter(self) -> None:
        self.tree.clear()
        query = self.search_field.text().strip()
        show_all_levels = self.show_all_levels_checkbox.isChecked()

        by_group: dict[tuple[int, str | None], list[dimensions_service.UnifiedDetailAccountRow]] = {}
        for e in self._entries:
            by_group.setdefault((e.dimension_type_id, e.person_group_code), []).append(e)

        for key in sorted(by_group, key=lambda k: _group_label(by_group[k][0].group_name)):
            entries = by_group[key]
            if show_all_levels:
                self._add_group_hierarchy(entries, query)
            else:
                self._add_group_leaves(entries, query)

        self.tree.expandAll()
        for i in range(len(_COLUMNS)):
            self.tree.resizeColumnToContents(i)

    def _make_group_item(self, group_name: str, color: str | None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([_group_label(group_name), "", "", ""])
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        if color:
            for col in range(len(_COLUMNS)):
                item.setForeground(col, QBrush(QColor(color)))
        self.tree.addTopLevelItem(item)
        return item

    def _make_leaf_item(
        self, parent: QTreeWidgetItem, e: dimensions_service.UnifiedDetailAccountRow, color: str | None
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem(
            [e.full_code, e.name or "—", str(e.level_no), "فعال" if e.is_active else "غیرفعال"]
        )
        item.setData(0, Qt.UserRole, (e.dimension_type_id, e.detail_account_id, e.person_group_code, e.group_name))
        if color:
            for col in range(len(_COLUMNS)):
                item.setForeground(col, QBrush(QColor(color)))
        parent.addChild(item)
        return item

    def _add_group_leaves(
        self, entries: list[dimensions_service.UnifiedDetailAccountRow], query: str
    ) -> None:
        parent_ids = {e.parent_detail_account_id for e in entries if e.parent_detail_account_id is not None}
        leaves = [e for e in entries if e.detail_account_id not in parent_ids]
        matched = [e for e in leaves if self._matches_query(e, query)]
        if not matched:
            return
        color = next((e.color for e in entries if e.color), None)
        group_item = self._make_group_item(entries[0].group_name, color)
        for e in sorted(matched, key=lambda r: r.full_code):
            self._make_leaf_item(group_item, e, color)

    def _add_group_hierarchy(
        self, entries: list[dimensions_service.UnifiedDetailAccountRow], query: str
    ) -> None:
        by_id = {e.detail_account_id: e for e in entries}
        matched_ids = {e.detail_account_id for e in entries if self._matches_query(e, query)}
        if not matched_ids:
            return
        included_ids = set(matched_ids)
        for matched_id in matched_ids:
            cur = by_id.get(matched_id)
            while cur is not None and cur.parent_detail_account_id is not None:
                included_ids.add(cur.parent_detail_account_id)
                cur = by_id.get(cur.parent_detail_account_id)

        children_by_parent: dict[int | None, list[dimensions_service.UnifiedDetailAccountRow]] = {}
        for e in entries:
            if e.detail_account_id in included_ids:
                children_by_parent.setdefault(e.parent_detail_account_id, []).append(e)
        for siblings in children_by_parent.values():
            siblings.sort(key=lambda r: r.full_code)

        color = next((e.color for e in entries if e.color), None)
        group_item = self._make_group_item(entries[0].group_name, color)

        def add_children(parent_item: QTreeWidgetItem, parent_id: int | None) -> None:
            for e in children_by_parent.get(parent_id, []):
                leaf_item = self._make_leaf_item(parent_item, e, color)
                add_children(leaf_item, e.detail_account_id)

        add_children(group_item, None)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.UserRole)
        if data is None:
            return  # گرهِ سرگروه — چیزی برایِ باز کردن نیست
        dimension_type_id, detail_account_id, person_group_code, _group_name = data
        self.open_entry(dimension_type_id, detail_account_id, person_group_code)

    def open_entry(self, dimension_type_id: int, detail_account_id: int, person_group_code: str | None) -> None:
        # طبقِ درخواستِ صریح («تعریفِ تفصیلی‌ها همه در یک فرم باشد»): همه‌ی
        # انواع (اشخاص و ۷ نوعِ خاص و گروه‌هایِ ساده) حالا از همینِ یک فرمِ
        # واحد («GL_DIM») باز می‌شوند، نه صفحه‌هایِ جداگانه‌یِ قبلی.
        combo_data = ("person", person_group_code) if person_group_code else ("dim", dimension_type_id)
        self._main_window.open_screen(
            "GL_DIM", then=lambda screen: screen.select_type_and_edit(combo_data, detail_account_id)
        )

    # --- دکمه‌ی «تفصیلیِ جدید» ------------------------------------------------
    def _new_entry_actions(self, company_id: int) -> list[tuple[str, Callable[[], None]]]:
        """فهرستِ (برچسب، تابعِ ناوبری) برایِ منویِ «تفصیلیِ جدید» — جدا از
        خودِ QMenu تا بدونِ نیاز به exec (که مودال/بلاک‌کننده است) قابلِ‌تست باشد."""
        actions: list[tuple[str, Callable[[], None]]] = []
        for group in dimensions_service.list_person_groups(company_id):
            combo_data = ("person", group.code)
            actions.append((
                group.name,
                lambda combo_data=combo_data: self._main_window.open_screen(
                    "GL_DIM", then=lambda screen: screen.select_type_for_new_entry(combo_data)
                ),
            ))

        for dim_type in dimensions_service.list_dimension_types(company_id):
            label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(dim_type.code, dim_type.code)
            combo_data = ("dim", dim_type.dimension_type_id)
            actions.append((
                label,
                lambda combo_data=combo_data: self._main_window.open_screen(
                    "GL_DIM", then=lambda screen: screen.select_type_for_new_entry(combo_data)
                ),
            ))
        return actions

    def _show_new_entry_menu(self) -> None:
        company_id = session.current_company.company_id if session.current_company else None
        if company_id is None:
            return
        menu = QMenu(self)
        for label, callback in self._new_entry_actions(company_id):
            menu.addAction(label, callback)
        menu.exec(self.new_entry_button.mapToGlobal(self.new_entry_button.rect().bottomLeft()))
