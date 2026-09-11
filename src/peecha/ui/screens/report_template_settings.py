"""تنظیماتِ رجیستریِ گزارش‌هایِ حرفه‌ای -- طبقِ درخواستِ صریح («برایِ هر
فرم بتوان چند گزارشِ نام‌گذاری‌شده تعریف/ویرایش/اجرا کرد»). طبقِ اصلاحِ
صریحِ بعدی («یک پنل به‌ازایِ هر فرم فضایِ زیادی می‌گیرد»): همه‌یِ
گزارش‌هایِ همه‌یِ فرم‌ها در یک جدولِ واحد (فرم/نام/پیش‌فرض) نشان داده
می‌شوند؛ ستونِ «فرم» مشخص می‌کند هر ردیف مالِ کدام فرم است، و دکمه‌های
عملیات (افزودن/ویرایش/تغییرِ نام/پیش‌فرض/حذف) رویِ همان یک جدول کار
می‌کنند -- افزودنِ فرمِ جدید هیچ فضایِ اضافه‌ای در این صفحه نمی‌گیرد،
فقط ردیف‌هایِ بیشتری به همان جدول اضافه می‌شود."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.reporting import jasper_bridge
from peecha.reporting.registry import FORM_DEFINITIONS
from peecha.services import report_templates as templates_service

_COLUMNS = ["فرم", "نامِ گزارش", "پیش‌فرض"]


def _company_id() -> int | None:
    return app_session.current_company.company_id if app_session.current_company else None


class _NewReportDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("گزارشِ جدید")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("فرم"))
        self.form_combo = QComboBox()
        for form_code, definition in FORM_DEFINITIONS.items():
            self.form_combo.addItem(definition["label"], form_code)
        layout.addWidget(self.form_combo)
        layout.addWidget(QLabel("نامِ گزارش"))
        self.name_field = QLineEdit()
        layout.addWidget(self.name_field)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_form_code(self) -> str:
        return self.form_combo.currentData()

    def name(self) -> str:
        return self.name_field.text().strip()


class _ReportTemplatesTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        title = QLabel("گزارش‌هایِ حرفه‌ای")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        add_button = QPushButton("➕ گزارشِ جدید")
        add_button.setObjectName("primaryIconButton")
        add_button.clicked.connect(self._add)
        layout.addWidget(add_button, alignment=Qt.AlignLeft)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        button_cluster = QWidget()
        button_cluster.setLayoutDirection(Qt.LeftToRight)
        buttons = QHBoxLayout(button_cluster)
        buttons.setContentsMargins(0, 0, 0, 0)

        edit_button = QPushButton("✏️ ویرایش")
        edit_button.setToolTip("بازکردنِ فایلِ این گزارش در Jaspersoft Studio")
        edit_button.clicked.connect(self._edit)
        buttons.addWidget(edit_button)

        rename_button = QPushButton("🖊️ تغییرِ نام")
        rename_button.clicked.connect(self._rename)
        buttons.addWidget(rename_button)

        default_button = QPushButton("⭐ پیش‌فرض")
        default_button.setToolTip("این گزارش پیش‌فرضِ همان فرم شود")
        default_button.clicked.connect(self._set_default)
        buttons.addWidget(default_button)

        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(44)
        delete_button.setToolTip("حذفِ این گزارش")
        delete_button.clicked.connect(self._delete)
        buttons.addWidget(delete_button)
        layout.addWidget(button_cluster)

        self._rows: list[templates_service.ReportTemplateRow] = []

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        self._rows = templates_service.list_all_templates(company_id)
        self.table.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            form_label = FORM_DEFINITIONS.get(row.form_code, {}).get("label", row.form_code)
            form_item = QTableWidgetItem(form_label)
            form_item.setData(Qt.UserRole, row.report_template_id)
            self.table.setItem(row_index, 0, form_item)
            self.table.setItem(row_index, 1, QTableWidgetItem(row.name))
            self.table.setItem(row_index, 2, QTableWidgetItem("✓" if row.is_default else ""))

    def _selected_row(self) -> templates_service.ReportTemplateRow | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        return self._rows[selected[0].row()]

    def _add(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        dialog = _NewReportDialog(self)
        if dialog.exec() != QDialog.Accepted or not dialog.name():
            return
        try:
            templates_service.create_template(company_id, dialog.selected_form_code(), dialog.name())
        except (ValueError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _rename(self) -> None:
        company_id = _company_id()
        row = self._selected_row()
        if company_id is None or row is None:
            QMessageBox.information(self, "تغییرِ نام", "ابتدا یک گزارش را انتخاب کنید.")
            return
        new_name, ok = QInputDialog.getText(self, "تغییرِ نام", "نامِ جدید:", text=row.name)
        if not ok or not new_name.strip():
            return
        try:
            templates_service.rename_template(row.report_template_id, company_id, new_name.strip())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _set_default(self) -> None:
        company_id = _company_id()
        row = self._selected_row()
        if company_id is None or row is None:
            QMessageBox.information(self, "پیش‌فرض", "ابتدا یک گزارش را انتخاب کنید.")
            return
        templates_service.set_default(row.report_template_id, company_id)
        self.refresh()

    def _delete(self) -> None:
        company_id = _company_id()
        row = self._selected_row()
        if company_id is None or row is None:
            QMessageBox.information(self, "حذف", "ابتدا یک گزارش را انتخاب کنید.")
            return
        confirm = QMessageBox.question(self, "حذف", "این گزارش حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            templates_service.delete_template(row.report_template_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _edit(self) -> None:
        company_id = _company_id()
        row = self._selected_row()
        if company_id is None or row is None:
            QMessageBox.information(self, "ویرایش", "ابتدا یک گزارش را انتخاب کنید.")
            return
        try:
            path = templates_service.get_template_path(row.report_template_id, company_id)
            opened = jasper_bridge.open_path_for_editing(path)
        except (ValueError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "ویرایش", str(exc))
            return
        if not opened:
            QMessageBox.information(
                self,
                "ویرایش",
                "Jaspersoft Studio به‌صورتِ خودکار پیدا نشد.\n\n"
                f"مسیرِ فایلِ قالب: {path}\n\n"
                "این فایل را به‌صورتِ دستی در Jaspersoft Studio باز کنید، یا "
                "مسیرِ اجراییِ Studio را در متغیرِ محیطیِ PEECHA_JASPER_STUDIO_PATH تنظیم کنید.",
            )


class _ReportPickerDialog(QDialog):
    """طبقِ درخواستِ صریح («در فرم‌ها فقط دکمهٔ گزارش را بزنیم، لیستِ
    گزارش‌هایِ تخصیص‌داده‌شده را نمایش و انتخاب و اجرا کنیم»)."""

    def __init__(self, parent: QWidget, rows: list[templates_service.ReportTemplateRow]) -> None:
        super().__init__(parent)
        self.setWindowTitle("انتخابِ گزارش")
        self._rows = rows
        self._selected_id: int | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("کدام گزارش اجرا شود؟"))
        self.table = QTableWidget(len(rows), 1)
        self.table.setHorizontalHeaderLabels(["نام"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for row_index, row in enumerate(rows):
            label = f"⭐ {row.name}" if row.is_default else row.name
            item = QTableWidgetItem(label)
            self.table.setItem(row_index, 0, item)
        default_index = next((i for i, r in enumerate(rows) if r.is_default), 0)
        self.table.selectRow(default_index)
        self.table.cellDoubleClicked.connect(lambda *_: self.accept())
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_template(self) -> templates_service.ReportTemplateRow | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self._rows[row]


def pick_report_template(parent: QWidget, company_id: int, form_code: str) -> templates_service.ReportTemplateRow | None:
    """گزارش‌هایِ تخصیص‌داده‌شده‌یِ این فرم را می‌آورد -- اگر هیچ‌کدام
    تعریف نشده باشد پیامِ راهنما نشان می‌دهد، اگر فقط یکی باشد بدونِ
    دیالوگ همان را برمی‌گرداند، وگرنه دیالوگِ انتخاب باز می‌شود."""
    rows = templates_service.list_templates(company_id, form_code)
    if not rows:
        QMessageBox.information(
            parent,
            "گزارش",
            "برایِ این فرم هنوز هیچ گزارشی تعریف نشده — از «تنظیماتِ سیستم ›  گزارش‌ها» یک گزارش اضافه کنید.",
        )
        return None
    if len(rows) == 1:
        return rows[0]
    dialog = _ReportPickerDialog(parent, rows)
    if dialog.exec() != QDialog.Accepted:
        return None
    return dialog.selected_template()
