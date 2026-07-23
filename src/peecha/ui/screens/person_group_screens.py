"""مشتریان/تامین‌کنندگان/پرسنل — معادلِ Qt برایِ person_group_screens.py/.kv در Kivy.

یک کلاسِ پایه (فهرست + فرمِ ساخت/ویرایش/حذف) + سه زیرکلاسِ نازک که فقط
FIELD_SPECS و متدهایِ سرویسِ خودشان را مشخص می‌کنند — دقیقاً همان الگویِ
Kivy (PersonGroupScreenBase)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import detail_dimensions as dimensions_service

_FIELD_LABELS = {
    "economic_code": "کدِ اقتصادی",
    "national_id": "شناسه/کدِ ملی",
    "phone": "تلفن",
    "mobile": "موبایل",
    "address": "آدرس",
    "credit_limit": "سقفِ اعتبار",
    "notes": "یادداشت",
    "bank_account_no": "شماره‌حسابِ بانکی",
    "personnel_no": "شماره‌ی پرسنلی",
    "position_title": "سمت",
    "hire_date": "تاریخِ استخدام",
}

_COLUMNS = ["وضعیت", "نام", "کد"]


class PersonGroupScreenBase(QWidget):
    FIELD_SPECS: tuple[tuple[str, str], ...] = ()  # (field_key, kind) — kind: text/decimal/date
    EMPTY_TEXT = ""

    def __init__(self) -> None:
        super().__init__()
        self._rows_by_id: dict[int, dict] = {}
        self._editing_id: int | None = None
        self._extra_widgets: dict[str, QWidget] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.list_title = QLabel("")
        self.list_title.setObjectName("pageTitle")
        layout.addWidget(self.list_title)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return panel

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        self.form_title = QLabel("افزودنِ موردِ تازه")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        grid = QGridLayout()
        grid.setSpacing(8)
        row = 0

        grid.addWidget(QLabel("کد"), row, 0)
        self.code_field = QLineEdit()
        grid.addWidget(self.code_field, row, 1)
        row += 1

        grid.addWidget(QLabel("نام"), row, 0)
        self.name_field = QLineEdit()
        grid.addWidget(self.name_field, row, 1)
        row += 1

        for field_key, kind in self.FIELD_SPECS:
            grid.addWidget(QLabel(_FIELD_LABELS.get(field_key, field_key)), row, 0)
            widget: QWidget
            if kind == "decimal":
                widget = QDoubleSpinBox()
                widget.setRange(0, 10_000_000_000)
                widget.setDecimals(2)
            elif kind == "date":
                widget = QDateEdit()
                widget.setCalendarPopup(True)
                widget.setSpecialValueText(" ")
                widget.setDate(widget.minimumDate())
            else:
                widget = QLineEdit()
            grid.addWidget(widget, row, 1)
            self._extra_widgets[field_key] = widget
            row += 1

        self.active_checkbox = QCheckBox("فعال")
        self.active_checkbox.setChecked(True)
        grid.addWidget(self.active_checkbox, row, 1)
        row += 1

        layout.addLayout(grid)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.save_button = QPushButton("افزودن")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)

        self.cancel_button = QPushButton("انصراف")
        self.cancel_button.setObjectName("flatButton")
        self.cancel_button.clicked.connect(self._reset_form)
        self.cancel_button.setVisible(False)
        buttons.addWidget(self.cancel_button)

        self.delete_button = QPushButton("حذف")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)
        buttons.addWidget(self.delete_button)

        layout.addLayout(buttons)
        layout.addStretch(1)
        return panel

    # --- هوک‌های زیرکلاس ---------------------------------------------------
    def _list_rows(self, company_id: int) -> list[dict]:
        raise NotImplementedError

    def _create(self, company_id: int, code: str, name: str, extra: dict) -> None:
        raise NotImplementedError

    def _update(self, detail_account_id: int, company_id: int, code: str, name: str, is_active: bool, extra: dict) -> None:
        raise NotImplementedError

    def _delete_row(self, detail_account_id: int, company_id: int) -> None:
        raise NotImplementedError

    # --- منطقِ مشترک --------------------------------------------------------
    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.status_label.setText("")
        company_id = self._company_id()
        rows = self._list_rows(company_id) if company_id is not None else []
        self._rows_by_id = {r["detail_account_id"]: r for r in rows}
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                "فعال" if row["is_active"] else "غیرفعال",
                row["name"] or "—",
                row["code"],
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row["detail_account_id"])
                self.table.setItem(row_index, col_index, item)
        self._reset_form(keep_status=True)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        detail_account_id = self.table.item(row, 0).data(Qt.UserRole)
        self._load_into_form(detail_account_id)

    def _load_into_form(self, detail_account_id: int) -> None:
        row = self._rows_by_id.get(detail_account_id)
        if row is None:
            return
        self._editing_id = detail_account_id
        self.form_title.setText(f"ویرایشِ «{row['name'] or row['code']}»")
        self.code_field.setText(row["code"])
        self.name_field.setText(row["name"] or "")
        self.active_checkbox.setChecked(row["is_active"])
        for field_key, kind in self.FIELD_SPECS:
            widget = self._extra_widgets[field_key]
            value = row.get(field_key)
            if kind == "decimal":
                widget.setValue(float(value) if value is not None else 0)
            elif kind == "date":
                if value:
                    widget.setDate(value)
                else:
                    widget.setDate(widget.minimumDate())
            else:
                widget.setText(str(value) if value is not None else "")
        self.save_button.setText("ذخیره‌ی تغییرات")
        self.cancel_button.setVisible(True)
        self.delete_button.setVisible(True)
        self.status_label.setText(f"در حالِ ویرایشِ «{row['name'] or row['code']}»")

    def _reset_form(self, *, keep_status: bool = False) -> None:
        self._editing_id = None
        self.form_title.setText("افزودنِ موردِ تازه")
        if not keep_status:
            self.status_label.setText("")
        self.code_field.clear()
        self.name_field.clear()
        self.active_checkbox.setChecked(True)
        for field_key, kind in self.FIELD_SPECS:
            widget = self._extra_widgets[field_key]
            if kind == "decimal":
                widget.setValue(0)
            elif kind == "date":
                widget.setDate(widget.minimumDate())
            else:
                widget.clear()
        self.save_button.setText("افزودن")
        self.cancel_button.setVisible(False)
        self.delete_button.setVisible(False)
        self.table.clearSelection()

    def _collect_extra_fields(self) -> dict:
        extra: dict = {}
        for field_key, kind in self.FIELD_SPECS:
            widget = self._extra_widgets[field_key]
            if kind == "decimal":
                value = widget.value()
                extra[field_key] = decimal.Decimal(str(value)) if value else None
            elif kind == "date":
                qdate = widget.date()
                if qdate == widget.minimumDate():
                    extra[field_key] = None
                else:
                    extra[field_key] = datetime.date(qdate.year(), qdate.month(), qdate.day())
            else:
                text = widget.text().strip()
                extra[field_key] = text or None
        return extra

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self.status_label.setText("هیچ شرکتی انتخاب نشده است.")
            return
        code = self.code_field.text().strip()
        name = self.name_field.text().strip()
        if not code or not name:
            self.status_label.setText("کد و نام را وارد کنید.")
            return

        extra = self._collect_extra_fields()
        try:
            if self._editing_id is not None:
                self._update(self._editing_id, company_id, code, name, self.active_checkbox.isChecked(), extra)
            else:
                self._create(company_id, code, name, extra)
        except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
            self.status_label.setText(f"خطا: {exc}")
            return

        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        row = self._rows_by_id.get(self._editing_id)
        confirm = QMessageBox.question(
            self,
            "حذف",
            f"«{row['name'] or row['code']}» حذف شود؟ این کار قابلِ بازگشت نیست.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self._delete_row(self._editing_id, company_id)
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"خطا: {exc}")
            return
        self.refresh()


_CUSTOMER_FIELD_SPECS = (
    ("economic_code", "text"), ("national_id", "text"), ("phone", "text"), ("mobile", "text"),
    ("address", "text"), ("credit_limit", "decimal"), ("notes", "text"),
)
_SUPPLIER_FIELD_SPECS = (
    ("economic_code", "text"), ("national_id", "text"), ("phone", "text"), ("mobile", "text"),
    ("address", "text"), ("bank_account_no", "text"), ("notes", "text"),
)
_PERSONNEL_FIELD_SPECS = (
    ("national_id", "text"), ("personnel_no", "text"), ("position_title", "text"), ("phone", "text"),
    ("mobile", "text"), ("hire_date", "date"), ("bank_account_no", "text"), ("notes", "text"),
)


class CustomersScreen(PersonGroupScreenBase):
    FIELD_SPECS = _CUSTOMER_FIELD_SPECS
    EMPTY_TEXT = "هنوز مشتری‌ای تعریف نشده است."

    def __init__(self) -> None:
        super().__init__()
        self.list_title.setText("مشتریان")

    def _list_rows(self, company_id: int) -> list[dict]:
        return dimensions_service.list_customers(company_id)

    def _create(self, company_id: int, code: str, name: str, extra: dict) -> None:
        dimensions_service.create_customer(company_id=company_id, code=code, name=name, **extra)

    def _update(self, detail_account_id, company_id, code, name, is_active, extra) -> None:
        dimensions_service.update_customer(
            detail_account_id=detail_account_id, company_id=company_id, code=code, name=name,
            is_active=is_active, **extra,
        )

    def _delete_row(self, detail_account_id: int, company_id: int) -> None:
        dimensions_service.delete_customer(detail_account_id, company_id)

    # معادلِ edit_person در Kivy — برای مسیرِ فهرستِ واحدِ تفصیلی‌ها
    def edit_person(self, detail_account_id: int) -> None:
        self._load_into_form(detail_account_id)


class SuppliersScreen(PersonGroupScreenBase):
    FIELD_SPECS = _SUPPLIER_FIELD_SPECS
    EMPTY_TEXT = "هنوز تامین‌کننده‌ای تعریف نشده است."

    def __init__(self) -> None:
        super().__init__()
        self.list_title.setText("تامین‌کنندگان")

    def _list_rows(self, company_id: int) -> list[dict]:
        return dimensions_service.list_suppliers(company_id)

    def _create(self, company_id: int, code: str, name: str, extra: dict) -> None:
        dimensions_service.create_supplier(company_id=company_id, code=code, name=name, **extra)

    def _update(self, detail_account_id, company_id, code, name, is_active, extra) -> None:
        dimensions_service.update_supplier(
            detail_account_id=detail_account_id, company_id=company_id, code=code, name=name,
            is_active=is_active, **extra,
        )

    def _delete_row(self, detail_account_id: int, company_id: int) -> None:
        dimensions_service.delete_supplier(detail_account_id, company_id)

    def edit_person(self, detail_account_id: int) -> None:
        self._load_into_form(detail_account_id)


class PersonnelScreen(PersonGroupScreenBase):
    FIELD_SPECS = _PERSONNEL_FIELD_SPECS
    EMPTY_TEXT = "هنوز پرسنلی تعریف نشده است."

    def __init__(self) -> None:
        super().__init__()
        self.list_title.setText("پرسنل")

    def _list_rows(self, company_id: int) -> list[dict]:
        return dimensions_service.list_personnel(company_id)

    def _create(self, company_id: int, code: str, name: str, extra: dict) -> None:
        dimensions_service.create_personnel(company_id=company_id, code=code, name=name, **extra)

    def _update(self, detail_account_id, company_id, code, name, is_active, extra) -> None:
        dimensions_service.update_personnel(
            detail_account_id=detail_account_id, company_id=company_id, code=code, name=name,
            is_active=is_active, **extra,
        )

    def _delete_row(self, detail_account_id: int, company_id: int) -> None:
        dimensions_service.delete_personnel(detail_account_id, company_id)

    def edit_person(self, detail_account_id: int) -> None:
        self._load_into_form(detail_account_id)
