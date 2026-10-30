"""R316: ویرایشگر مشترک «عنوان فیلدها» و «ترجمه‌ها» برای همهٔ فرم‌های برنامه.

فهرست فرم‌ها از منوی برنامه ساخته می‌شود؛ با انتخاب هر فرم، خود آن فرم ساخته و همهٔ
برچسب‌ها، گزینه‌ها، سرستون‌ها و دکمه‌هایش فهرست می‌شوند. متن دلخواه در services.ui_texts
ذخیره و هنگام ساخت فرم‌ها (app_style) اعمال می‌شود."""

from __future__ import annotations

import csv

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha.nav_catalog import flatten_nav_items, flatten_nav_items_with_breadcrumb
from peecha.services import languages as languages_service
from peecha.services import translations as translations_service
from peecha.services import ui_texts
from peecha.ui import ui_text_apply

NAV_ENTRY = "__nav__"
_SETTINGS_SCREEN = "system_settings"
_COL_KIND, _COL_SOURCE, _COL_VALUE = 0, 1, 2
_FILTERS = [("همهٔ متن‌ها", "all"), ("فقط تغییرکرده", "changed"), ("فقط بدون متن دلخواه", "empty")]


def _icon_button(glyph: str, tip: str, kind: str = "") -> QPushButton:
    b = QPushButton(glyph)
    b.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    b.setToolTip(tip)
    b.setAccessibleName(tip)
    b.setProperty("label", tip)
    b.setFixedWidth(48 if kind == "primary" else 44)
    b.setCursor(Qt.PointingHandCursor)
    return b


def _main_window():
    for w in QApplication.topLevelWidgets():
        if hasattr(w, "_screens") and hasattr(w, "register_screen"):
            return w
    return None


def _default_provider(screen_name: str):
    mw = _main_window()
    return mw._screens.get(screen_name) if mw is not None else None


def form_entries(provider=None) -> list[tuple[str, str]]:
    """(کلید، مسیر منو) همهٔ فرم‌ها؛ تنظیمات سیستم به‌ازای هر زبانهٔ اصلی جدا."""
    screens = {i["code"]: i.get("screen") for i in flatten_nav_items()}
    out, used = [], set()
    for code, _label, crumb in flatten_nav_items_with_breadcrumb():
        screen = screens.get(code)
        if not screen or screen in used:
            continue
        used.add(screen)
        if screen == _SETTINGS_SCREEN:
            continue
        out.append((f"screen:{screen}", crumb))
    settings = (provider or _default_provider)(_SETTINGS_SCREEN)
    tabs = getattr(settings, "tabs", None)
    if isinstance(tabs, QTabWidget):
        for i in range(tabs.count()):
            out.append((f"settings:{i}", f"تنظیمات سیستم › {tabs.tabText(i)}"))
    return out


class UiTextEditor(QWidget):
    """mode='labels' عنوان دلخواه (همهٔ زبان‌ها، پیش‌فرض: زبان اصلی)، mode='translate' ترجمه (زبان‌های دیگر)."""

    def __init__(self, mode: str = "labels") -> None:
        super().__init__()
        self.mode = mode
        self.screen_provider = _default_provider
        self.entries: list[tuple[str, str]] = []
        self.rows: list[tuple[str, str]] = []
        self._saved: dict[str, str] = {}
        self._entry_key: str | None = None
        translate = mode == "translate"
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        header = QFrame()
        header.setObjectName("card")
        top = QHBoxLayout(header)
        top.setContentsMargins(10, 6, 10, 6)
        title = QLabel("ترجمه‌ها" if translate else "عنوان فیلدها")
        title.setObjectName("pageTitle")
        top.addWidget(title)
        top.addSpacing(12)
        top.addWidget(QLabel("زبان مقصد" if translate else "زبان"))
        self.language_combo = QComboBox()
        self.language_combo.setMinimumWidth(160)
        self.language_combo.currentIndexChanged.connect(lambda _i: self.load_entry())
        top.addWidget(self.language_combo)
        top.addStretch(1)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("sectionHint")
        top.addWidget(self.progress_label)
        outer.addWidget(header)

        hint = QLabel(
            "متن هر فیلد، گزینه، سرستون یا دکمه را به زبان مقصد بنویسید. با انتخاب همین زبان از «زبان فعال» بالای "
            "برنامه، فرم‌ها هنگام باز شدن با این متن‌ها نمایش داده می‌شوند." if translate else
            "فرم را از فهرست انتخاب کنید و برای هر عنوان، متن دلخواه را بنویسید. خانهٔ خالی یعنی همان متن اصلی. "
            "تغییرها روی فرم‌هایی که از این به بعد باز می‌شوند اعمال می‌شود؛ خود اطلاعات و منطق فرم تغییر نمی‌کند.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.form_search = QLineEdit()
        self.form_search.setPlaceholderText("جستجوی فرم")
        self.form_search.setClearButtonEnabled(True)
        self.form_search.textChanged.connect(self._filter_forms)
        ll.addWidget(self.form_search)
        self.form_list = QListWidget()
        self.form_list.setWordWrap(True)
        self.form_list.setStyleSheet("QListWidget::item { min-height: 32px; padding: 3px 6px; }")
        self.form_list.currentItemChanged.connect(lambda cur, _prev: self.load_entry())
        ll.addWidget(self.form_list, stretch=1)
        left.setMinimumWidth(260)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        self.text_search = QLineEdit()
        self.text_search.setPlaceholderText("جستجو در متن‌ها")
        self.text_search.setClearButtonEnabled(True)
        self.text_search.textChanged.connect(lambda _t: self._apply_filter())
        filters.addWidget(self.text_search, stretch=1)
        self.filter_combo = QComboBox()
        for label, code in _FILTERS:
            self.filter_combo.addItem(label, code)
        self.filter_combo.currentIndexChanged.connect(lambda _i: self._apply_filter())
        filters.addWidget(self.filter_combo)
        rl.addLayout(filters)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["نوع", "متن اصلی", "ترجمه" if translate else "عنوان دلخواه"])
        self.table.setProperty("latin_digits", True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        self.table.horizontalHeader().setSectionResizeMode(_COL_KIND, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(_COL_SOURCE, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(_COL_VALUE, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        rl.addWidget(self.table, stretch=1)
        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        rl.addWidget(self.status_label)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, stretch=1)

        footer = QFrame()
        footer.setObjectName("card")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(8, 6, 8, 6)
        self.save_btn = _icon_button("💾", "ذخیرهٔ تغییرات", "primary")
        self.reset_btn = _icon_button("↩️", "بازگشت ردیف‌های انتخاب‌شده به متن اصلی")
        self.export_btn = _icon_button("📤", "خروجی متن‌های این فرم (CSV) برای ترجمه بیرون از برنامه")
        self.import_btn = _icon_button("📥", "ورود متن‌ها از فایل CSV")
        self.refresh_btn = _icon_button("🔄", "به‌روزرسانی")
        self.save_btn.clicked.connect(lambda: self.save())
        self.reset_btn.clicked.connect(lambda: self.reset_selected())
        self.export_btn.clicked.connect(lambda: self.export_csv())
        self.import_btn.clicked.connect(lambda: self.import_csv())
        self.refresh_btn.clicked.connect(lambda: self.refresh())
        for b in (self.save_btn, self.reset_btn, self.export_btn, self.import_btn, self.refresh_btn):
            fl.addWidget(b)
        fl.addStretch(1)
        outer.addWidget(footer)
        self._loading = False

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        languages = languages_service.list_languages()
        if self.mode == "translate":
            languages = [lang for lang in languages if not lang.is_default]
        current = self.language_combo.currentData()
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        for lang in languages:
            self.language_combo.addItem(lang.native_name + (" (اصلی)" if lang.is_default else ""), lang.language_id)
        index = self.language_combo.findData(current) if current is not None else -1
        if index < 0 and self.mode != "translate":
            index = next((i for i, lang in enumerate(languages) if lang.is_default), 0)
        self.language_combo.setCurrentIndex(max(index, 0))
        self.language_combo.blockSignals(False)
        if not languages:
            self.status_label.setText("هیچ زبان دیگری تعریف نشده است؛ از «تنظیمات › عمومی › زبان‌ها» یک زبان اضافه کنید."
                                      if self.mode == "translate" else "هیچ زبانی تعریف نشده است.")
        else:
            self.status_label.setText("")
        key = self._entry_key
        try:
            self.entries = form_entries(self.screen_provider)
        except Exception as exc:  # noqa: BLE001 -- ساخت فهرست نباید صفحه را از کار بیندازد
            self.entries = []
            self.status_label.setText(f"فهرست فرم‌ها ساخته نشد: {exc}")
        if self.mode == "translate":
            self.entries.insert(0, (NAV_ENTRY, "منوها و زبانه‌های تنظیمات"))
        self.form_list.blockSignals(True)
        self.form_list.clear()
        for entry_key, crumb in self.entries:
            item = QListWidgetItem(crumb)
            item.setData(Qt.UserRole, entry_key)
            item.setToolTip(crumb)
            self.form_list.addItem(item)
        self.form_list.blockSignals(False)
        self._filter_forms(self.form_search.text())
        if key is not None:
            self.select_entry(key)
        else:
            self._fill([])

    def _filter_forms(self, text: str) -> None:
        needle = (text or "").strip()
        for row in range(self.form_list.count()):
            item = self.form_list.item(row)
            item.setHidden(bool(needle) and needle not in item.text())

    def select_entry(self, entry_key: str) -> bool:
        for row in range(self.form_list.count()):
            if self.form_list.item(row).data(Qt.UserRole) == entry_key:
                self.form_list.setCurrentRow(row)
                self.load_entry()
                return True
        return False

    def _entry_widgets(self, entry_key: str) -> list[QWidget]:
        if entry_key.startswith("screen:"):
            w = self.screen_provider(entry_key.split(":", 1)[1])
            return [w] if w is not None else []
        if entry_key.startswith("settings:"):
            settings = self.screen_provider(_SETTINGS_SCREEN)
            tabs = getattr(settings, "tabs", None)
            index = int(entry_key.split(":", 1)[1])
            return [tabs.widget(index)] if isinstance(tabs, QTabWidget) and index < tabs.count() else []
        return []

    def load_entry(self) -> None:
        item = self.form_list.currentItem()
        language_id = self.language_combo.currentData()
        if item is None or language_id is None:
            self._fill([])
            return
        entry_key = item.data(Qt.UserRole)
        self._entry_key = entry_key
        if entry_key == NAV_ENTRY:
            labels = translations_service.list_translatable_labels()
            existing = translations_service.list_translations_for_language(language_id)
            self.rows = [("منو", label.source_label, label.code) for label in labels]
            self._saved = {label.code: existing.get(label.code, "") for label in labels}
            self._fill(self.rows)
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            rows: list[tuple[str, str]] = []
            for w in self._entry_widgets(entry_key):
                for kind, text in ui_text_apply.harvest(w):
                    if all(text != r[1] for r in rows):
                        rows.append((kind, text))
        except Exception as exc:  # noqa: BLE001
            rows = []
            self.status_label.setText(f"این فرم برای فهرست‌کردن متن‌ها باز نشد: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        self.rows = [(kind, text, text) for kind, text in rows]
        values = ui_texts.current_values(language_id, [text for _k, text in rows])
        self._saved = {text: values.get(text, "") for _k, text in rows}
        self._fill(self.rows)

    def _fill(self, rows: list[tuple[str, str, str]]) -> None:
        self._loading = True
        self.table.setRowCount(len(rows))
        for r, (kind, source, row_key) in enumerate(rows):
            kind_item = QTableWidgetItem(kind)
            kind_item.setFlags(kind_item.flags() & ~Qt.ItemIsEditable)
            source_item = QTableWidgetItem(source)
            source_item.setFlags(source_item.flags() & ~Qt.ItemIsEditable)
            source_item.setData(Qt.UserRole, row_key)
            value_item = QTableWidgetItem(self._saved.get(row_key, ""))
            self.table.setItem(r, _COL_KIND, kind_item)
            self.table.setItem(r, _COL_SOURCE, source_item)
            self.table.setItem(r, _COL_VALUE, value_item)
        self._loading = False
        self._apply_filter()
        self._update_progress()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != _COL_VALUE:
            return
        self._update_progress()

    def _update_progress(self) -> None:
        total = self.table.rowCount()
        done = sum(1 for r in range(total) if (self.table.item(r, _COL_VALUE).text() or "").strip())
        word = "ترجمه شده" if self.mode == "translate" else "عنوان دلخواه دارد"
        self.progress_label.setText(numerals.to_persian_digits(f"{done} از {total} {word}") if total else "")

    def _apply_filter(self) -> None:
        needle = (self.text_search.text() or "").strip()
        mode = self.filter_combo.currentData()
        for r in range(self.table.rowCount()):
            source = self.table.item(r, _COL_SOURCE).text()
            value = (self.table.item(r, _COL_VALUE).text() or "").strip()
            hide = bool(needle) and needle not in source and needle not in value
            if mode == "changed":
                hide = hide or not value
            elif mode == "empty":
                hide = hide or bool(value)
            self.table.setRowHidden(r, hide)

    # ------------------------------------------------------------------
    def set_value(self, source: str, value: str) -> bool:
        for r in range(self.table.rowCount()):
            if self.table.item(r, _COL_SOURCE).text() == ui_texts.normalize(source):
                self.table.item(r, _COL_VALUE).setText(value)
                return True
        return False

    def pending(self) -> list[tuple[str, str]]:
        out = []
        for r in range(self.table.rowCount()):
            row_key = self.table.item(r, _COL_SOURCE).data(Qt.UserRole)
            value = (self.table.item(r, _COL_VALUE).text() or "").strip()
            if value != (self._saved.get(row_key) or ""):
                out.append((row_key, value))
        return out

    def save(self) -> int:
        language_id = self.language_combo.currentData()
        if language_id is None:
            self.status_label.setText("ابتدا زبان را انتخاب کنید.")
            return 0
        changes = self.pending()
        if not changes:
            self.status_label.setText("تغییری برای ذخیره نیست.")
            return 0
        try:
            if self._entry_key == NAV_ENTRY:
                for code, value in changes:
                    translations_service.set_translation(code, language_id, value)
            else:
                ui_texts.save(language_id, changes)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return 0
        for row_key, value in changes:
            self._saved[row_key] = value
        self.status_label.setText(numerals.to_persian_digits(
            f"{len(changes)} متن ذخیره شد؛ فرم‌ها از بار بعدی که باز شوند با متن جدید نمایش داده می‌شوند."))
        self._update_progress()
        return len(changes)

    def reset_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if not rows:
            self.status_label.setText("ردیف‌هایی را که باید به متن اصلی برگردند انتخاب کنید.")
            return
        for r in rows:
            self.table.item(r, _COL_VALUE).setText("")
        self.status_label.setText("برای ثبت بازگشت به متن اصلی، تغییرها را ذخیره کنید.")

    def export_csv(self, path: str | None = None) -> str | None:
        if path is None:
            path, _f = QFileDialog.getSaveFileName(self, "خروجی متن‌ها", "ui_texts.csv", "CSV (*.csv)")
        if not path:
            return None
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["متن اصلی", "ترجمه" if self.mode == "translate" else "عنوان دلخواه"])
            for r in range(self.table.rowCount()):
                writer.writerow([self.table.item(r, _COL_SOURCE).text(), self.table.item(r, _COL_VALUE).text()])
        self.status_label.setText("فایل ساخته شد.")
        return path

    def import_csv(self, path: str | None = None) -> int:
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self, "ورود متن‌ها", "", "CSV (*.csv)")
        if not path:
            return 0
        try:
            with open(path, encoding="utf-8-sig", newline="") as fh:
                data = {row[0].strip(): row[1].strip() for row in csv.reader(fh) if len(row) >= 2}
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.warning(self, "ورود متن‌ها", f"فایل خوانده نشد: {exc}")
            return 0
        count = 0
        for r in range(self.table.rowCount()):
            source = self.table.item(r, _COL_SOURCE).text()
            if source in data and data[source] != self.table.item(r, _COL_VALUE).text():
                self.table.item(r, _COL_VALUE).setText(data[source])
                count += 1
        self.status_label.setText(numerals.to_persian_digits(f"{count} متن از فایل وارد شد؛ برای ثبت، ذخیره کنید."))
        return count
