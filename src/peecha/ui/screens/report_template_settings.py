"""تنظیماتِ رجیستریِ گزارش‌هایِ حرفه‌ای -- طبقِ درخواستِ صریح («برایِ هر
فرم بتوان چند گزارشِ نام‌گذاری‌شده تعریف/ویرایش/اجرا کرد»): هر فرمِ
پشتیبانی‌شده (peecha.reporting.registry.FORM_DEFINITIONS) یک پنلِ مستقل
دارد؛ افزودن یک کپیِ تازه از قالبِ پایه‌یِ همان فرم می‌سازد، ویرایش همان
کپی را در Jaspersoft Studio باز می‌کند."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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


def _company_id() -> int | None:
    return app_session.current_company.company_id if app_session.current_company else None


class _ReportTemplatesTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._tables: dict[str, QTableWidget] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(16)
        for form_code, definition in FORM_DEFINITIONS.items():
            layout.addWidget(self._build_section(form_code, definition["label"]), stretch=1)

    def _build_section(self, form_code: str, label: str) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        title = QLabel(label)
        title.setObjectName("pageTitle")
        panel_layout.addWidget(title)

        add_button = QPushButton("➕ گزارشِ جدید")
        add_button.setObjectName("primaryIconButton")
        add_button.clicked.connect(lambda: self._add(form_code))
        panel_layout.addWidget(add_button, alignment=Qt.AlignLeft)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["نام", "پیش‌فرض"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        panel_layout.addWidget(table)

        button_cluster = QWidget()
        button_cluster.setLayoutDirection(Qt.LeftToRight)
        buttons = QHBoxLayout(button_cluster)
        buttons.setContentsMargins(0, 0, 0, 0)

        edit_button = QPushButton("✏️ ویرایش")
        edit_button.setToolTip("بازکردنِ فایلِ این گزارش در Jaspersoft Studio")
        edit_button.clicked.connect(lambda: self._edit(form_code))
        buttons.addWidget(edit_button)

        rename_button = QPushButton("🖊️ تغییرِ نام")
        rename_button.clicked.connect(lambda: self._rename(form_code))
        buttons.addWidget(rename_button)

        default_button = QPushButton("⭐ پیش‌فرض")
        default_button.setToolTip("این گزارش پیش‌فرضِ این فرم شود")
        default_button.clicked.connect(lambda: self._set_default(form_code))
        buttons.addWidget(default_button)

        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(44)
        delete_button.setToolTip("حذفِ این گزارش")
        delete_button.clicked.connect(lambda: self._delete(form_code))
        buttons.addWidget(delete_button)
        panel_layout.addWidget(button_cluster)

        self._tables[form_code] = table
        return panel

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        for form_code, table in self._tables.items():
            rows = templates_service.list_templates(company_id, form_code)
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                name_item = QTableWidgetItem(row.name)
                name_item.setData(Qt.UserRole, row.report_template_id)
                table.setItem(row_index, 0, name_item)
                table.setItem(row_index, 1, QTableWidgetItem("✓" if row.is_default else ""))

    def _selected_id(self, form_code: str) -> int | None:
        table = self._tables[form_code]
        selected = table.selectedItems()
        if not selected:
            return None
        return table.item(selected[0].row(), 0).data(Qt.UserRole)

    def _add(self, form_code: str) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        name, ok = QInputDialog.getText(self, "گزارشِ جدید", "نامِ گزارش:")
        if not ok or not name.strip():
            return
        try:
            templates_service.create_template(company_id, form_code, name.strip())
        except (ValueError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _rename(self, form_code: str) -> None:
        company_id = _company_id()
        report_template_id = self._selected_id(form_code)
        if company_id is None or report_template_id is None:
            QMessageBox.information(self, "تغییرِ نام", "ابتدا یک گزارش را انتخاب کنید.")
            return
        new_name, ok = QInputDialog.getText(self, "تغییرِ نام", "نامِ جدید:")
        if not ok or not new_name.strip():
            return
        try:
            templates_service.rename_template(report_template_id, company_id, new_name.strip())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _set_default(self, form_code: str) -> None:
        company_id = _company_id()
        report_template_id = self._selected_id(form_code)
        if company_id is None or report_template_id is None:
            QMessageBox.information(self, "پیش‌فرض", "ابتدا یک گزارش را انتخاب کنید.")
            return
        templates_service.set_default(report_template_id, company_id)
        self.refresh()

    def _delete(self, form_code: str) -> None:
        company_id = _company_id()
        report_template_id = self._selected_id(form_code)
        if company_id is None or report_template_id is None:
            QMessageBox.information(self, "حذف", "ابتدا یک گزارش را انتخاب کنید.")
            return
        confirm = QMessageBox.question(self, "حذف", "این گزارش حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            templates_service.delete_template(report_template_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _edit(self, form_code: str) -> None:
        company_id = _company_id()
        report_template_id = self._selected_id(form_code)
        if company_id is None or report_template_id is None:
            QMessageBox.information(self, "ویرایش", "ابتدا یک گزارش را انتخاب کنید.")
            return
        try:
            path = templates_service.get_template_path(report_template_id, company_id)
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
