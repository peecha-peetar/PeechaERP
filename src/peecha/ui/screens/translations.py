"""ترجمه‌ها — معادلِ Qt برایِ ترجمه‌یِ برچسب‌هایِ ناوبری (ساید‌بار/ریبون/
زیرفرم‌هایِ تنظیمات) به زبان‌هایِ غیرِپیش‌فرض.

طبقِ حسابرسیِ صریح، این صفحه قبلاً یک PlaceholderScreen خالی بود (معادلِ
Qtِ صفحه‌ی قدیمیِ Kivy هرگز ساخته نشده بود). ستونِ «ترجمه» این‌جا مستقیماً
قابلِ‌ویرایش است؛ با ذخیره، shell_window.py با اولین تغییرِ سوییچرِ زبانِ
هدر آن‌ها را واقعاً رویِ ساید‌بار/ریبون اعمال می‌کند."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha.services import languages as languages_service
from peecha.services import translations as translations_service
from peecha.ui.widgets import FieldHelpMixin

_COLUMNS = ["ترجمه", "متنِ فارسیِ اصلی"]
_SOURCE_COL = 1
_TRANSLATION_COL = 0


class TranslationsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._labels: list[translations_service.TranslatableLabel] = []
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("ترجمه‌ها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "ترجمه‌یِ عنوانِ منوهایِ ناوبری (ساید‌بار/ریبون) و زیرفرم‌هایِ تنظیماتِ سیستم به زبانِ انتخابی. "
            "با انتخابِ همین زبان از سوییچرِ «زبانِ فعال» در هدرِ برنامه، این ترجمه‌ها واقعاً نمایش داده می‌شوند."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        selectors = QHBoxLayout()
        selectors.addWidget(QLabel("زبانِ مقصد"))
        self.language_combo = QComboBox()
        self.language_combo.currentIndexChanged.connect(self._reload_table)
        selectors.addWidget(self.language_combo)
        selectors.addStretch(1)
        layout.addLayout(selectors)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(_SOURCE_COL, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(_TRANSLATION_COL, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        save_row = QHBoxLayout()
        save_button = QPushButton("ذخیره‌یِ تغییرات")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save_all)
        save_row.addWidget(save_button)
        save_row.addStretch(1)
        layout.addLayout(save_row)

        self.set_field_help([
            (
                self.language_combo,
                "زبانی که برایِ ترجمه ویرایش می‌کنید. برایِ خودِ زبانِ پیش‌فرض (فارسی) ترجمه معنایی ندارد "
                "چون متنِ اصلیِ منوها همیشه فارسی است.",
            ),
        ])

    def refresh(self) -> None:
        languages = [lang for lang in languages_service.list_languages() if not lang.is_default]
        current_id = self.language_combo.currentData()
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        for lang in languages:
            self.language_combo.addItem(lang.native_name, lang.language_id)
        if current_id is not None:
            index = self.language_combo.findData(current_id)
            if index >= 0:
                self.language_combo.setCurrentIndex(index)
        self.language_combo.blockSignals(False)
        if not languages:
            self.status_label.setText(
                "هیچ زبانِ غیرِپیش‌فرضی تعریف نشده — از صفحه‌ی «زبان‌ها» یک زبانِ تازه اضافه کنید."
            )
        else:
            self.status_label.setText("")
        self._reload_table()

    def _reload_table(self) -> None:
        self._loading = True
        language_id = self.language_combo.currentData()
        self._labels = translations_service.list_translatable_labels()
        existing = translations_service.list_translations_for_language(language_id) if language_id else {}

        self.table.setRowCount(len(self._labels))
        for row_index, label in enumerate(self._labels):
            translation_item = QTableWidgetItem(existing.get(label.code, ""))
            translation_item.setData(Qt.UserRole, label.code)
            source_item = QTableWidgetItem(label.source_label)
            source_item.setFlags(source_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_index, _TRANSLATION_COL, translation_item)
            self.table.setItem(row_index, _SOURCE_COL, source_item)
        self._loading = False

    def _save_all(self) -> None:
        language_id = self.language_combo.currentData()
        if language_id is None:
            self.status_label.setText("ابتدا یک زبانِ مقصد انتخاب کنید.")
            return
        for row_index in range(self.table.rowCount()):
            item = self.table.item(row_index, _TRANSLATION_COL)
            code = item.data(Qt.UserRole)
            translations_service.set_translation(code, language_id, item.text())
        self.status_label.setText("")
        QMessageBox.information(self, "ذخیره شد", "ترجمه‌ها ذخیره شدند.")
