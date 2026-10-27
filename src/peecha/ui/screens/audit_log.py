"""رد حسابرسی — معادل Qt برای audit_log.py/.kv در Kivy.

فقط‌خواندنی (طبق ماهیت تغییرناپذیر خود جدول)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import audit as audit_service
from peecha.ui import audit_format
from peecha.ui.widgets import FieldHelpMixin

_COLUMNS = ["تاریخ/ساعت", "کاربر", "عملیات", "شناسه", "نوع موجودیت", "جزئیات"]

_ACTION_LABELS = {"CREATE": "ایجاد", "UPDATE": "ویرایش", "DELETE": "حذف", "APPROVE": "تایید", "REVERSE": "برگشت",
                  "MERGE": "ادغام", "SUBMIT": "ارسال", "REJECT": "رد", "DELEGATE": "واگذاری", "ESCALATE": "ارجاع به مافوق",
                  "EXECUTE": "ثبت نهایی", "PUBLISH": "انتشار", "CANCEL": "لغو", "RETRY": "تلاش دوباره", "RESOLVE": "حل",
                  "COMMENT": "یادداشت", "START": "شروع", "COMPLETE": "انجام", "LOGIN": "ورود", "LOGIN_FAIL": "ورود ناموفق",
                  "LOCK": "قفل حساب"}
_ENTITY_TYPE_LABELS = {"ChartOfAccount": "حساب", "JournalEntry": "سند حسابداری", "StockDocument": "سند انبار",
                       "WarehouseTask": "وظیفهٔ انبار", "CycleCountSession": "شمارش انبار", "CommercialDocument": "سند فروش/خرید",
                       "BinLocation": "محل انبار", "ItemStorageProfile": "شرایط نگهداری کالا", "ProductionOrder": "دستور تولید",
                       "QcInspection": "بازرسی کیفیت"}


class AuditLogScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[audit_service.ActivityLogRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel("وقایع کاربران")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel("رویدادهای ایجاد/ویرایش/حذف اطلاعات کسب‌وکاری — فقط‌خواندنی و تغییرناپذیر.")
        hint.setObjectName("sectionHint")
        layout.addWidget(hint)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("نوع موجودیت"))
        self.entity_type_combo = QComboBox()
        self.entity_type_combo.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self.entity_type_combo)
        filter_row.addStretch(1)
        self.details_button = QPushButton("🔍")
        self.details_button.setObjectName("iconButton")
        self.details_button.setFixedWidth(44)
        self.details_button.setToolTip("نمایش جزئیات رویداد انتخاب‌شده")
        self.details_button.setProperty("label", "نمایش جزئیات رویداد انتخاب‌شده")
        self.details_button.clicked.connect(self._show_selected)
        filter_row.addWidget(self.details_button)
        layout.addLayout(filter_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("sectionHint")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._show_changes)
        layout.addWidget(self.table, stretch=1)

        self.set_field_help([
            (
                self.entity_type_combo,
                "فقط رویدادهای مربوط به یک نوع اطلاعات را نشان بده، مثلاً فقط تغییرات حساب‌ها یا فقط اسناد. "
                "«همهٔ انواع» یعنی بدون فیلتر. برای دیدن جزئیات کامل یک رویداد، روی ردیفش دابل‌کلیک کنید.",
            ),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        entity_types = audit_service.list_entity_types()
        self.entity_type_combo.blockSignals(True)
        self.entity_type_combo.clear()
        self.entity_type_combo.addItem("همهٔ انواع", None)
        for et in entity_types:
            self.entity_type_combo.addItem(_ENTITY_TYPE_LABELS.get(et) or audit_format.entity_label(et), et)
        self.entity_type_combo.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self) -> None:
        company_id = self._company_id()
        entity_type = self.entity_type_combo.currentData()
        self._rows = audit_service.list_activity_log(company_id, entity_type)
        self.status_label.setText("هنوز رویدادی ثبت نشده است." if not self._rows
                                  else numerals.to_persian_digits(f"{len(self._rows)} رویداد یافت شد."))
        self.table.setRowCount(len(self._rows))
        for row_index, r in enumerate(self._rows):
            values = [
                numerals.format_jalali_datetime(r.created_at),
                r.user_full_name or "سیستم",
                _ACTION_LABELS.get(r.action, r.action),
                numerals.to_persian_digits(str(r.entity_id)),
                _ENTITY_TYPE_LABELS.get(r.entity_type) or audit_format.entity_label(r.entity_type),
                audit_format.summary(r.changes),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.changes)
                if col_index == 5:
                    item.setToolTip(value)
                self.table.setItem(row_index, col_index, item)

    def _show_selected(self) -> None:
        items = self.table.selectedItems()
        if items:
            self._show_changes(items[0].row(), 0)

    def details_dialog(self, row: int) -> QDialog:
        """جزئیات خوانای یک رویداد: خلاصه + جدول «موضوع / پیش از تغییر / پس از تغییر»."""
        changes = self.table.item(row, 0).data(Qt.UserRole)
        dlg = QDialog(self)
        dlg.setWindowTitle("جزئیات رویداد")
        dlg.resize(720, 460)
        layout = QVBoxLayout(dlg)
        head = QLabel(" — ".join(self.table.item(row, c).text() for c in (0, 1, 2, 4))
                      + f" (شناسه {self.table.item(row, 3).text()})")
        head.setObjectName("cardTitle")
        head.setWordWrap(True)
        layout.addWidget(head)
        lines = audit_format.rows(changes)
        table = QTableWidget(len(lines), 3)
        table.setHorizontalHeaderLabels(["موضوع", "پیش از تغییر", "پس از تغییر / مقدار"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setWordWrap(True)
        for r, (subject, before, after) in enumerate(lines):
            for c, text in enumerate((subject, before, after)):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                table.setItem(r, c, item)
        layout.addWidget(table, stretch=1)
        if not lines:
            empty = QLabel("برای این رویداد جزئیات دیگری ثبت نشده است.")
            empty.setObjectName("sectionHint")
            layout.addWidget(empty)
        self.details_table = table
        return dlg

    def _show_changes(self, row: int, _column: int) -> None:
        dlg = self.details_dialog(row)
        runner = getattr(self, "dialog_runner", None)
        runner(dlg) if runner is not None else dlg.exec()
