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

from peecha import session
from peecha.services import detail_dimensions as dimensions_service

_GROUP_SCREEN_BY_PERSON_CODE = {
    "CUSTOMER": "customers",
    "SUPPLIER": "suppliers",
    "PERSONNEL": "personnel",
}

# طبقِ درخواستِ صریح: ۷ نوعِ «فرمِ خاص» صفحه‌ی اختصاصیِ خودشان را دارند —
# کلیک روی ردیفِ آن‌ها در فهرستِ واحد باید به همان صفحه برود، نه صفحه‌ی
# عمومیِ گروه‌هایِ «ساده» (GL_DIM).
_NAV_CODE_BY_DIMENSION_CODE = {
    "INVENTORY_ITEM": "GL_INVENTORY_ITEMS",
    "FIXED_ASSET": "GL_FIXED_ASSETS",
    "BANK_ACCOUNT": "GL_BANK_ACCOUNTS",
    "CASH_BOX": "GL_CASH_BOXES",
    "PETTY_CASH": "GL_PETTY_CASHES",
    "COST_CENTER": "GL_COST_CENTERS",
    "PROJECT": "GL_PROJECTS",
}

_COLUMNS = ["نام", "کد", "سطح", "وضعیت"]


def _group_label(group_name: str) -> str:
    """گروه‌هایِ اشخاص از قبل با نامِ فارسی (مثلِ «مشتری») ذخیره شده‌اند؛
    گروه‌هایِ عمومی با کدِ خام (مثلِ «CASH_BOX») که این‌جا به برچسبِ فارسی
    ترجمه می‌شود — کدِ خام برایِ مسیریابی دست‌نخورده می‌ماند."""
    return dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(group_name, group_name)


class DetailAccountsListScreen(QWidget):
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
        self.new_entry_button = QPushButton("+ تفصیلیِ جدید")
        self.new_entry_button.setObjectName("primaryButton")
        self.new_entry_button.clicked.connect(self._show_new_entry_menu)
        header_row.addWidget(self.new_entry_button)
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

    def refresh(self) -> None:
        company_id = session.current_company.company_id if session.current_company else None
        self._entries = dimensions_service.list_all_detail_accounts(company_id) if company_id is not None else []
        self._apply_filter()

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
            [e.name or "—", e.full_code, str(e.level_no), "فعال" if e.is_active else "غیرفعال"]
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
        dimension_type_id, detail_account_id, person_group_code, group_name = data
        self.open_entry(dimension_type_id, detail_account_id, person_group_code, group_name)

    def open_entry(
        self, dimension_type_id: int, detail_account_id: int, person_group_code: str | None, group_name: str = ""
    ) -> None:
        target_code = _GROUP_SCREEN_BY_PERSON_CODE.get(person_group_code or "")
        if target_code is not None:
            nav_code = {"customers": "GL_CUSTOMERS", "suppliers": "GL_SUPPLIERS", "personnel": "GL_PERSONNEL"}[target_code]
            self._main_window.open_screen(nav_code, then=lambda screen: screen.edit_person(detail_account_id))
            return

        specialized_nav_code = _NAV_CODE_BY_DIMENSION_CODE.get(group_name)
        if specialized_nav_code is not None:
            self._main_window.open_screen(
                specialized_nav_code, then=lambda screen: screen.edit_detail_account(detail_account_id)
            )
            return

        self._main_window.open_screen(
            "GL_DIM", then=lambda screen: screen.select_type_and_edit(dimension_type_id, detail_account_id)
        )

    # --- دکمه‌ی «تفصیلیِ جدید» ------------------------------------------------
    def _new_entry_actions(self, company_id: int) -> list[tuple[str, Callable[[], None]]]:
        """فهرستِ (برچسب، تابعِ ناوبری) برایِ منویِ «تفصیلیِ جدید» — جدا از
        خودِ QMenu تا بدونِ نیاز به exec (که مودال/بلاک‌کننده است) قابلِ‌تست باشد."""
        actions: list[tuple[str, Callable[[], None]]] = []
        for group in dimensions_service.list_person_groups(company_id):
            nav_code = {"CUSTOMER": "GL_CUSTOMERS", "SUPPLIER": "GL_SUPPLIERS", "PERSONNEL": "GL_PERSONNEL"}.get(
                group.code
            )
            if nav_code is None:
                continue
            actions.append((group.name, lambda nav_code=nav_code: self._main_window.open_screen(nav_code)))

        for dim_type in dimensions_service.list_dimension_types(company_id):
            specialized_nav_code = _NAV_CODE_BY_DIMENSION_CODE.get(dim_type.code)
            if specialized_nav_code is not None:
                label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(dim_type.code, dim_type.code)
                actions.append((label, lambda nav_code=specialized_nav_code: self._main_window.open_screen(nav_code)))
            else:
                actions.append((
                    dim_type.code,
                    lambda type_id=dim_type.dimension_type_id: self._main_window.open_screen(
                        "GL_DIM", then=lambda screen: screen.select_type_for_new_entry(type_id)
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
