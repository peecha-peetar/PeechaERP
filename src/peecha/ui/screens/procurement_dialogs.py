"""دیالوگ‌هایِ R240 در فرمِ سند: علتِ لغو، تاریخچهٔ تغییرات، تاریخِ تحویلِ ردیف‌ها."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from peecha import numerals
from peecha.services import commercial_documents as documents_service
from peecha.services import procurement_masters as masters_service
from peecha.ui.widgets import JalaliDateEdit

_FIELD_LABELS = {
    "quantity": "مقدار", "unit_price": "فی", "discount_amount": "تخفیف", "tax_percent": "درصدِ مالیات",
    "expected_delivery_date": "تاریخِ تحویلِ ردیف", "document_date": "تاریخِ سند", "counterparty_detail_account_id": "طرفِ حساب",
    "warehouse_id": "انبار", "requested_delivery_date": "تاریخِ تحویل", "purchase_type_id": "نوعِ خرید", "status_code": "وضعیت",
}
_ACTIONS = {"ADD_LINE": "افزودنِ ردیف", "UPDATE_LINE": "ویرایشِ ردیف", "DELETE_LINE": "حذفِ ردیف",
            "UPDATE_HEADER": "ویرایشِ سرِ سند", "STATUS": "تغییرِ وضعیت"}
_STATUSES = {"DRAFT": "پیش‌نویس", "CONFIRMED": "تاییدشده", "APPROVED": "تصویب‌شده", "POSTED": "ثبتِ نهایی", "CANCELLED": "لغوشده"}


def _dialog(parent, title: str) -> tuple[QDialog, QVBoxLayout]:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLayoutDirection(Qt.RightToLeft)
    return dialog, QVBoxLayout(dialog)


class CancellationReasonDialog:
    @staticmethod
    def ask(parent, company_id: int | None) -> tuple[int | None, str | None] | None:
        """(علت، توضیح) یا None اگر کاربر انصراف داد."""
        dialog, layout = _dialog(parent, "علتِ لغو")
        layout.addWidget(QLabel("علتِ لغوِ این سند را انتخاب کنید:"))
        combo = QComboBox()
        combo.addItem("— بدونِ علت —", None)
        for reason in masters_service.list_cancellation_reasons(company_id, active_only=True) if company_id else []:
            combo.addItem(reason.name, reason.reason_id)
        layout.addWidget(combo)
        note = QLineEdit()
        note.setPlaceholderText("توضیح (اختیاری)")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.combo, dialog.note = combo, note
        CancellationReasonDialog.last = dialog
        if getattr(CancellationReasonDialog, "auto_answer", None) is not None:  # برایِ تستِ خودکار
            index, text = CancellationReasonDialog.auto_answer
            combo.setCurrentIndex(index)
            note.setText(text)
            return combo.currentData(), note.text().strip() or None
        if dialog.exec() != QDialog.Accepted:
            return None
        return combo.currentData(), note.text().strip() or None


def _format(field_name: str | None, value: str | None) -> str:
    if value is None:
        return ""
    if field_name == "status_code":
        return _STATUSES.get(value, value)
    return numerals.to_persian_digits(value)


class DocumentHistoryDialog(QDialog):
    def __init__(self, parent, document_id: int, users: dict[int, str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("تاریخچهٔ تغییرات و تاییدِ سند")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(900, 460)
        layout = QVBoxLayout(self)
        hint = QLabel("از R240: تغییرِ وضعیت‌ها و هر ویرایشی که پس از اولین تایید انجام شده ثبت می‌شود.")
        hint.setObjectName("sectionHint")
        layout.addWidget(hint)
        logs = documents_service.list_document_changes(document_id)
        self.table = QTableWidget(len(logs), 6)
        self.table.setHorizontalHeaderLabels(["زمان", "کاربر", "عملیات", "فیلد", "مقدارِ قبلی", "مقدارِ جدید"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for r, log in enumerate(logs):
            cells = [numerals.format_jalali_datetime(log.changed_at), users.get(log.user_id, ""), _ACTIONS.get(log.action, log.action),
                     _FIELD_LABELS.get(log.field_name, log.field_name or ""), _format(log.field_name, log.old_value),
                     _format(log.field_name, log.new_value)]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(text))
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class LineDeliveryDatesDialog(QDialog):
    """تاریخِ تحویلِ موردِ انتظارِ هر ردیف -- در هر وضعیتی جز لغو قابلِ‌تغییر."""

    def __init__(self, parent, document_id: int, company_id: int, item_labels: dict[int, str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("تاریخِ تحویلِ ردیف‌ها")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(700, 420)
        self._document_id, self._company_id = document_id, company_id
        doc, lines = documents_service.get_document(document_id, company_id)
        self._lines = lines
        layout = QVBoxLayout(self)
        hint = QLabel("ردیفی که تاریخ ندارد از «تاریخِ تحویلِ مورد انتظار»ِ سرِ سند پیروی می‌کند.")
        hint.setObjectName("sectionHint")
        layout.addWidget(hint)
        self.table = QTableWidget(len(lines), 3)
        self.table.setHorizontalHeaderLabels(["کالا", "مقدار", "تاریخِ تحویل"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.date_edits: list[JalaliDateEdit] = []
        for r, ln in enumerate(lines):
            self.table.setItem(r, 0, QTableWidgetItem(numerals.to_persian_digits(item_labels.get(ln.item_id, str(ln.item_id)))))
            self.table.setItem(r, 1, QTableWidgetItem(numerals.format_money(ln.quantity, 2, None)))
            edit = JalaliDateEdit()
            edit.setDate(ln.expected_delivery_date or doc.requested_delivery_date or doc.document_date)
            self.table.setCellWidget(r, 2, edit)
            self.date_edits.append(edit)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)

    def save(self) -> None:
        doc, _lines = documents_service.get_document(self._document_id, self._company_id)
        try:
            for ln, edit in zip(self._lines, self.date_edits):
                value = edit.date()
                if ln.expected_delivery_date is None and value == (doc.requested_delivery_date or doc.document_date):
                    continue  # همان تاریخِ سرِ سند -- ردیف بدونِ تاریخِ اختصاصی می‌ماند
                documents_service.set_line_expected_delivery_date(ln.line_id, self._document_id, self._company_id, value)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.accept()
