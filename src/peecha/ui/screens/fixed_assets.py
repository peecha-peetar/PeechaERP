"""صفحه‌های دارایی‌های ثابت — R265.

«دارایی‌ها» مرکز عملیات است: فهرست + صفحهٔ هر دارایی (نمای کلی، مالی، استهلاک، تراکنش‌ها، انتقال‌ها، تعمیرات، مدارک،
تاریخچه) و دکمه‌های عملیات. کاربر فقط «طبقه» را انتخاب می‌کند؛ حساب‌ها از تنظیمات طبقه می‌آیند.
ثبت دارایی با ویزارد هفت‌مرحله‌ای. همهٔ محاسبه/ثبت در سرویس‌های fixed_assets است.
"""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSplitter, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from peecha import decimals, numerals, session as app_session
from peecha.db.models import fixed_assets as fam
from peecha.services.fixed_assets import approval
from peecha.services.fixed_assets import assets as fa
from peecha.services.fixed_assets import common as fac
from peecha.services.fixed_assets import dashboard as fdash
from peecha.services.fixed_assets import depreciation as fd
from peecha.services.fixed_assets import documents as fdocs
from peecha.services.fixed_assets import events as fe
from peecha.services.fixed_assets import physical as fp
from peecha.ui import theme
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.costing import can
from peecha.ui.screens.purchase_dashboards import _ClickableKpiCard, _ProcurementDashboardBase, format_kpi
from peecha.ui.widgets import FormDrawer, JalaliDateEdit, confirm_and_delete, delete_button

ZERO = decimal.Decimal(0)


def P(value) -> str:
    return numerals.to_persian_digits(str(value))


def money(value) -> str:
    return decimals.format_amount(value) if value is not None else "—"


def dec(text: str) -> decimal.Decimal:
    text = numerals.to_ascii_digits((text or "").replace(",", "").replace("٬", "").strip())
    return decimal.Decimal(text) if text else ZERO


def company_id() -> int | None:
    return app_session.current_company.company_id if app_session.current_company else None


def user_id() -> int | None:
    return app_session.current_user.user_id if app_session.current_user else None


def combo(items, none_label: str | None = None) -> QComboBox:
    """فهرست جستجوپذیر (تایپ بخشی از نام)."""
    box = QComboBox()
    box.setEditable(True)
    box.setInsertPolicy(QComboBox.NoInsert)
    if none_label is not None:
        box.addItem(none_label, None)
    for label, data in items:
        box.addItem(P(label), data)
    completer = box.completer()
    if completer is not None:
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
    return box


def set_combo(box: QComboBox, data) -> None:
    idx = box.findData(data)
    box.setCurrentIndex(idx if idx >= 0 else 0)


def table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    t.horizontalHeader().setStretchLastSection(True)
    return t


def selected_data(t: QTableWidget):
    """شناسهٔ ردیف انتخاب‌شده (UserRole ستون اول) یا None."""
    items = t.selectedItems()
    return t.item(items[0].row(), 0).data(Qt.UserRole) if items else None


def fill(t: QTableWidget, rows: list[list], data: list | None = None) -> None:
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for col, value in enumerate(row):
            if isinstance(value, datetime.date):
                text = numerals.format_jalali_date(value)
            elif isinstance(value, decimal.Decimal):
                text = money(value)
            else:
                text = P(value if value is not None else "")
            item = QTableWidgetItem(text)
            if col == 0 and data is not None:
                item.setData(Qt.UserRole, data[r])
            t.setItem(r, col, item)


class Lookups:
    """فهرست‌های مشترک فهرستها (یک بار برای هر refresh)."""

    def __init__(self, cid: int) -> None:
        from peecha.services import chart_of_accounts as coa_service
        from peecha.services import detail_dimensions as dims
        from peecha.services import hr as hr_service
        from peecha.services import procurement_masters as masters

        cc_type = dims.get_specialized_dimension_type_id(cid, dims.COST_CENTER_CODE)
        pr_type = dims.get_specialized_dimension_type_id(cid, dims.PROJECT_CODE)
        self.cost_centers = [(f"{d.code} — {d.name or ''}", d.detail_account_id) for d in dims.list_detail_accounts(cid, cc_type)]
        self.projects = [(f"{d.code} — {d.name or ''}", d.detail_account_id) for d in dims.list_detail_accounts(cid, pr_type)]
        self.suppliers = [(f"{s['code']} — {s['name']}", s["detail_account_id"]) for s in dims.list_suppliers(cid)]
        self.customers = [(f"{s['code']} — {s['name']}", s["detail_account_id"]) for s in dims.list_customers(cid)]
        self.accounts = [(f"{a.full_code} — {a.name}", a.account_id) for a in coa_service.list_postable_accounts(cid)]
        self.employees = [(f"{e.employee_code} — {e.full_name}", e.employee_id) for e in hr_service.list_employees(cid)]
        self.branches = [(b.name, b.branch_id) for b in masters.list_branches(cid)]
        self.departments = [(d.name, d.org_unit_id) for d in masters.list_departments(cid)]
        self.categories = [(f"{c.code} — {c.name}", c.category_id) for c in fac.list_categories(cid, active_only=True)]
        self.groups = [(f"{g.code} — {g.name}", g.group_id) for g in fac.list_groups(cid)]
        self.locations = [(f"{loc.code} — {loc.name}", loc.location_id) for loc in fac.list_locations(cid)]


def scrolled(widget: QWidget, max_height: int = 0) -> QScrollArea:
    """فرم بلند در پنجرهٔ کوچک اسکرول بخورد، نه این‌که فیلدها له شوند و متن دیده نشود."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(widget)
    if max_height:
        area.setMinimumHeight(min(widget.sizeHint().height() + 4, max_height))
    return area


class FormDialog(QDialog):
    """فرم کوچک عملیات: [(کلید، برچسب، ویجت)] -- values() با تبدیل تاریخ/عدد/داده."""

    def __init__(self, title: str, fields: list[tuple[str, str, QWidget]], hint: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        if hint:
            note = QLabel(hint)
            note.setObjectName("sectionHint")
            note.setWordWrap(True)
            layout.addWidget(note)
        body = QWidget()
        form = QFormLayout(body)
        form.setContentsMargins(0, 0, 0, 0)
        self.widgets = {}
        for key, label, widget in fields:
            form.addRow(label, widget)
            self.widgets[key] = widget
        layout.addWidget(scrolled(body, 560), stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        out = {}
        for key, w in self.widgets.items():
            if isinstance(w, JalaliDateEdit):
                out[key] = w.date()
            elif isinstance(w, QComboBox):
                out[key] = w.currentData()
            elif isinstance(w, QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QTextEdit):
                out[key] = w.toPlainText().strip() or None
            elif isinstance(w, QLineEdit):
                text = w.text().strip()
                out[key] = dec(text) if w.property("numeric") else (text or None)
        return out


def num_field(value=None) -> QLineEdit:
    w = QLineEdit(P(value) if value is not None else "")
    w.setProperty("numeric", True)
    return w


def date_field(value: datetime.date | None = None) -> JalaliDateEdit:
    w = JalaliDateEdit()
    w.setDate(value or datetime.date.today())
    return w


# --- برچسبِ QR/بارکد ---------------------------------------------------------------------------------
def asset_label_image(asset, dpi: int = 300) -> QImage:
    from peecha.services import warehouse_locations as wl

    w, h = int(70 / 25.4 * dpi), int(35 / 25.4 * dpi)
    image = QImage(w, h, QImage.Format_RGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    rect = QRectF(w * 0.03, h * 0.06, w * 0.94, h * 0.88)
    matrix = wl.qr_matrix(fa.qr_payload(asset))
    cell = rect.height() / len(matrix)
    for r, row in enumerate(matrix):
        for col, bit in enumerate(row):
            if bit:
                painter.fillRect(QRectF(rect.left() + col * cell, rect.top() + r * cell, cell, cell), Qt.black)
    left = rect.left() + rect.height() + w * 0.03
    width = rect.right() - left
    font = QFont(painter.font())
    font.setPointSizeF(max(6.0, rect.height() / 9))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRectF(left, rect.top(), width, rect.height() * 0.22), int(Qt.AlignCenter), asset.asset_code)
    font.setBold(False)
    font.setPointSizeF(max(5.0, rect.height() / 13))
    painter.setFont(font)
    painter.drawText(QRectF(left, rect.top() + rect.height() * 0.22, width, rect.height() * 0.18), int(Qt.AlignCenter),
                     asset.name[:40])
    bits = wl.barcode_bits(asset.asset_code)
    unit, x = width / len(bits), left
    for bit in bits:
        if bit == "1":
            painter.fillRect(QRectF(x, rect.top() + rect.height() * 0.45, unit, rect.height() * 0.52), Qt.black)
        x += unit
    painter.end()
    return image


# =========================================================================================================
class FaDashboard(_ProcurementDashboardBase):
    TITLE = "داشبورد دارایی‌های ثابت"
    _KPI_STYLE = {"COUNT": ("🏭", "ACCENT"), "GROSS": ("💰", "CHART_TEAL"), "ACCUM": ("📉", "CHART_ORANGE"),
                  "NBV": ("📘", "ACCENT"), "IN_SERVICE": ("⚙", "SUCCESS"), "MAINTENANCE": ("🔧", "WARNING"),
                  "FULLY_DEPRECIATED": ("◌", "CHART_PURPLE"), "DISPOSED": ("✖", "DANGER")}

    def __init__(self, main_window=None) -> None:
        super().__init__(main_window)
        from peecha.ui.screens.dashboard import build_chart_card

        self.cards, self._kpis = {}, {}
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, (code, (icon, color)) in enumerate(self._KPI_STYLE.items()):
            card = _ClickableKpiCard("", icon, getattr(theme, color), lambda c=code: self._open_kpi(c))
            self.cards[code] = card
            grid.addWidget(card, i // 4, i % 4)
        self.body_layout.addLayout(grid)
        title = QLabel("هشدارها")
        title.setObjectName("cardTitle")
        self.body_layout.addWidget(title)
        self.alerts_table = table(["هشدار", "تعداد"])
        self.alerts_table.setMaximumHeight(170)
        self.body_layout.addWidget(self.alerts_table)
        charts = QGridLayout()
        self.chart_views = {}
        for i, (key, chart_title, report_code, options) in enumerate(fdash.CHART_TITLES):
            card, view = build_chart_card(chart_title)
            view.setMinimumHeight(240)
            link = QPushButton("گزارش ←")
            link.setObjectName("flatButton")
            link.clicked.connect(lambda _c=False, r=report_code, o=options: self.open_report(r, o))
            card.layout().addWidget(link, alignment=Qt.AlignLeft)
            self.chart_views[key] = view
            charts.addWidget(card, i // 2, i % 2)
        self.body_layout.addLayout(charts)

    def open_report(self, report_code: str, options: dict | None = None) -> None:
        if self._main_window is None:
            return
        date_from, date_to = self.date_from.date(), self.date_to.date()
        self._main_window.open_screen(f"INV_RPT_{report_code}", then=lambda s: s.apply_preset(date_from, date_to, options or {}))

    def _open_kpi(self, code: str) -> None:
        kpi = self._kpis.get(code)
        if kpi is not None:
            self.open_report(kpi.report_code, kpi.options)

    def reload(self) -> None:
        from peecha.ui.screens.dashboard import render_donut_chart
        from peecha.ui.screens.warehouse_dashboard import render_series_chart

        cid = company_id()
        if cid is None:
            return
        kpis, charts, alert_rows, _alerts = fdash.dashboard(cid, self.date_from.date(), self.date_to.date())
        self._kpis = {k.code: k for k in kpis}
        for code, kpi in self._kpis.items():
            card = self.cards[code]
            card._title_label.setText(kpi.title)
            card.set_value(format_kpi(kpi.value, kpi.kind, decimals.money_decimals()))
            card.setToolTip(f"فرمول: {kpi.formula}\nکلیک: گزارش مبدا")
        fill(self.alerts_table, [[label, n] for label, n in alert_rows])
        for key, data in charts.items():
            if data["kind"] == "donut":
                render_donut_chart(self.chart_views[key], [(P(lb), v) for lb, v in zip(data["labels"], data["series"]["تعداد"]) if v])
            else:
                render_series_chart(self.chart_views[key], data["labels"], data["series"])


# =========================================================================================================
class AssetWizard(QDialog):
    """ثبت دارایی در ۷ مرحله: اطلاعات ← بها ← طبقه ← روش استهلاک ← محل و مرکز هزینه ← بررسی ← ثبت."""

    STEPS = ("اطلاعات دارایی", "بهای خرید", "طبقه‌بندی", "روش استهلاک", "محل و مرکز هزینه", "بررسی", "ثبت")

    def __init__(self, lookups: Lookups, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ثبت دارایی")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(620)
        self.lk = lookups
        self.created_asset_id: int | None = None
        outer = QVBoxLayout(self)
        self.step_label = QLabel("")
        self.step_label.setObjectName("pageTitle")
        outer.addWidget(self.step_label)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, stretch=1)
        w = self.w = {}
        # ۱) اطلاعات
        w["asset_code"], w["name"] = QLineEdit(), QLineEdit()
        w["asset_type_code"] = combo([(v, k) for k, v in fac.TYPE_LABELS.items()])
        set_combo(w["asset_type_code"], "EQUIPMENT")
        w["brand"], w["model"], w["serial_no"], w["description"] = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self._page([("asset_code", "کد دارایی"), ("name", "نام"), ("asset_type_code", "نوع"), ("brand", "برند"), ("model", "مدل"),
                    ("serial_no", "شمارهٔ سریال"), ("description", "شرح")])
        # ۲) بها
        w["purchase"], w["transport"], w["installation"], w["other_cost"] = num_field(), num_field(), num_field(), num_field()
        w["offset_account"] = combo(lookups.accounts, "— حساب طرف مقابل (پرداختنی/بانک) —")
        w["supplier"] = combo(lookups.suppliers, "— تامین‌کننده —")
        w["acquisition_date"] = date_field()
        w["invoice_reference"] = QLineEdit()
        self._page([("purchase", "قیمت خرید"), ("transport", "حمل"), ("installation", "نصب/راه‌اندازی"),
                    ("other_cost", "سایر هزینه‌های سرمایه‌ای"), ("offset_account", "حساب طرف مقابل"), ("supplier", "تامین‌کننده"),
                    ("acquisition_date", "تاریخ تحصیل"), ("invoice_reference", "شمارهٔ فاکتور")])
        # ۳) طبقه
        w["category_id"] = combo(lookups.categories)
        w["group_id"] = combo(lookups.groups, "— بدون گروه —")
        self._page([("category_id", "طبقهٔ دارایی"), ("group_id", "گروه")],
                   "حساب‌های دارایی/استهلاک/سود و زیان از تنظیمات طبقه خوانده می‌شود.")
        # ۴) استهلاک
        w["depreciation_method"] = combo([(v, k) for k, v in fac.METHOD_LABELS.items()], "— پیش‌فرض طبقه —")
        w["useful_life"], w["residual_value"], w["declining_rate"] = num_field(), num_field(), num_field()
        w["useful_life_unit"] = combo([("ماه", "MONTH"), ("سال", "YEAR"), ("ساعت کار", "HOUR"), ("واحد تولید", "UNIT")])
        w["capitalize"] = QCheckBox("همین حالا سرمایه‌ای و در بهره‌برداری شود")
        w["capitalize"].setChecked(True)
        w["in_service_date"] = date_field()
        self._page([("depreciation_method", "روش استهلاک"), ("useful_life", "عمر مفید (خالی = پیش‌فرض)"),
                    ("useful_life_unit", "واحد عمر"), ("residual_value", "ارزش اسقاط"), ("declining_rate", "نرخ نزولی سالانه"),
                    ("capitalize", ""), ("in_service_date", "تاریخ بهره‌برداری")])
        # ۵) محل
        w["location_id"] = combo(lookups.locations, "— محل —")
        w["cost_center_detail_account_id"] = combo(lookups.cost_centers, "— مرکز هزینه (پیش‌فرض طبقه) —")
        w["custodian_employee_id"] = combo(lookups.employees, "— تحویل‌گیرنده —")
        w["branch_id"] = combo(lookups.branches, "— شعبه —")
        w["department_id"] = combo(lookups.departments, "— دپارتمان —")
        w["is_production_machine"] = QCheckBox("ماشین تولیدی")
        w["work_center_code"], w["standard_hours"] = QLineEdit(), num_field()
        self._page([("location_id", "محل"), ("cost_center_detail_account_id", "مرکز هزینه"), ("custodian_employee_id", "تحویل‌گیرنده"),
                    ("branch_id", "شعبه"), ("department_id", "دپارتمان"), ("is_production_machine", ""),
                    ("work_center_code", "مرکز کار"), ("standard_hours", "ساعت استاندارد سالانه")])
        # ۶) بررسی
        self.review = QLabel("")
        self.review.setWordWrap(True)
        page = QWidget()
        QVBoxLayout(page).addWidget(self.review)
        self.stack.addWidget(page)
        # ۷) ثبت
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        page = QWidget()
        QVBoxLayout(page).addWidget(self.result_label)
        self.stack.addWidget(page)
        nav = QHBoxLayout()
        self.back_button, self.next_button = QPushButton("قبلی"), QPushButton("بعدی")
        self.next_button.setObjectName("primaryButton")
        self.back_button.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        self.next_button.clicked.connect(self._next)
        nav.addWidget(self.back_button)
        nav.addStretch(1)
        nav.addWidget(self.next_button)
        outer.addLayout(nav)
        self.go(0)

    def _page(self, keys: list[tuple[str, str]], hint: str = "") -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        if hint:
            note = QLabel(hint)
            note.setObjectName("sectionHint")
            note.setWordWrap(True)
            layout.addWidget(note)
        form = QFormLayout()
        for key, label in keys:
            form.addRow(label, self.w[key])
        layout.addLayout(form)
        layout.addStretch(1)
        self.stack.addWidget(scrolled(page))

    def go(self, index: int) -> None:
        index = max(0, min(index, len(self.STEPS) - 1))
        if index == 5:
            self.review.setText(self._summary())
        self.stack.setCurrentIndex(index)
        self.step_label.setText(P(f"مرحلهٔ {index + 1} از ۷ -- {self.STEPS[index]}"))
        self.back_button.setEnabled(0 < index < 6)
        self.next_button.setText("ثبت" if index == 5 else ("بستن" if index == 6 else "بعدی"))

    def _next(self) -> None:
        i = self.stack.currentIndex()
        if i == 0 and not (self.w["asset_code"].text().strip() and self.w["name"].text().strip()):
            QMessageBox.warning(self, "ثبت دارایی", "کد و نام الزامی است.")
            return
        if i == 5:
            self.submit()
            return
        if i == 6:
            self.accept()
            return
        self.go(i + 1)

    def costs(self) -> list[fa.CostItem]:
        account, supplier = self.w["offset_account"].currentData(), self.w["supplier"].currentData()
        out = []
        for key, cost_type in (("purchase", "PURCHASE"), ("transport", "TRANSPORT"), ("installation", "INSTALLATION"),
                               ("other_cost", "OTHER")):
            amount = dec(self.w[key].text())
            if amount > 0:
                out.append(fa.CostItem(cost_type, amount, account, supplier if cost_type == "PURCHASE" else None,
                                       self.w["invoice_reference"].text().strip() or None))
        return out

    def fields(self) -> fa.AssetFields:
        w = self.w
        life, residual, rate = dec(w["useful_life"].text()), dec(w["residual_value"].text()), dec(w["declining_rate"].text())
        return fa.AssetFields(
            asset_code=w["asset_code"].text().strip(), name=w["name"].text().strip(), category_id=w["category_id"].currentData(),
            asset_type_code=w["asset_type_code"].currentData(), group_id=w["group_id"].currentData(),
            description=w["description"].text().strip() or None, brand=w["brand"].text().strip() or None,
            model=w["model"].text().strip() or None, serial_no=w["serial_no"].text().strip() or None,
            source_code="PURCHASE", acquisition_date=w["acquisition_date"].date(), residual_value=residual if residual else None,
            useful_life=life or None, useful_life_unit=w["useful_life_unit"].currentData() if life else "MONTH",
            depreciation_method=w["depreciation_method"].currentData(), declining_rate=rate or None,
            location_id=w["location_id"].currentData(), cost_center_detail_account_id=w["cost_center_detail_account_id"].currentData(),
            custodian_employee_id=w["custodian_employee_id"].currentData(), branch_id=w["branch_id"].currentData(),
            department_id=w["department_id"].currentData(), supplier_detail_account_id=w["supplier"].currentData(),
            invoice_reference=w["invoice_reference"].text().strip() or None,
            is_production_machine=w["is_production_machine"].isChecked(), work_center_code=w["work_center_code"].text().strip() or None,
            standard_hours=dec(w["standard_hours"].text()) or None)

    def _summary(self) -> str:
        f = self.fields()
        total = sum((c.amount for c in self.costs()), ZERO)
        return P("\n".join([
            f"کد/نام: {f.asset_code} -- {f.name}", f"طبقه: {self.w['category_id'].currentText()}",
            f"بهای تمام‌شده: {money(total)} ({len(self.costs())} جزء)",
            f"روش استهلاک: {self.w['depreciation_method'].currentText()} -- عمر: {f.useful_life or 'پیش‌فرض'}",
            f"محل: {self.w['location_id'].currentText()} -- مرکز هزینه: {self.w['cost_center_detail_account_id'].currentText()}",
            "سرمایه‌ای و در بهره‌برداری: " + ("بله" if self.w["capitalize"].isChecked() else "خیر")]))

    def submit(self) -> int | None:
        cid, uid = company_id(), user_id()
        try:
            asset_id = fa.create_asset(cid, uid, self.fields())
            items = self.costs()
            if items:
                fa.acquire(cid, uid, asset_id, self.w["acquisition_date"].date(), items, source_code="PURCHASE")
                if self.w["capitalize"].isChecked():
                    approval.request(cid, uid, "CAPITALIZE", asset_id, date=self.w["acquisition_date"].date(),
                                     in_service_date=self.w["in_service_date"].date())
        except ValueError as exc:
            QMessageBox.warning(self, "ثبت دارایی", str(exc))
            return None
        self.created_asset_id = asset_id
        self.result_label.setText(P(f"دارایی «{self.w['asset_code'].text().strip()}» ثبت شد."))
        self.go(6)
        return asset_id


# =========================================================================================================
@ms.styled
class AssetsScreen(QWidget):
    """مرکز عملیات دارایی."""

    scroll_in_mdi = True

    FORM = "fa_assets"
    TABS = ("نمای کلی", "مالی", "استهلاک", "تراکنش‌ها", "انتقال‌ها", "تعمیر و بهسازی", "مدارک", "تاریخچه")

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.asset = None
        self.lk: Lookups | None = None
        self.confirm = lambda text: QMessageBox.question(self, "دارایی", text) == QMessageBox.Yes
        self.dialog_runner = lambda dlg: dlg.exec() == QDialog.Accepted
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("دارایی‌های ثابت")
        title.setObjectName("pageTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو: کد، نام، سریال، بارکد یا QR")
        self.search.returnPressed.connect(self.reload_list)
        self.category_filter = QComboBox()
        self.status_filter = QComboBox()
        self.status_filter.addItem("— فعال‌ها —", "ACTIVE")
        self.status_filter.addItem("همه", None)
        for code, label in fac.STATUS_LABELS.items():
            self.status_filter.addItem(label, code)
        self.category_filter.currentIndexChanged.connect(self.reload_list)
        self.status_filter.currentIndexChanged.connect(self.reload_list)
        self.new_button = QPushButton("ثبت دارایی")
        self.new_button.setObjectName("primaryButton")
        self.new_button.clicked.connect(self.new_asset)
        outer.addWidget(ms.header_card(title, self.search, self.category_filter, self.status_filter, self.new_button))
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)
        split = QSplitter(Qt.Horizontal)
        self.list_table = table(["کد", "نام", "طبقه", "وضعیت", "ارزش دفتری"])
        self.list_table.itemSelectionChanged.connect(self._selected)
        split.addWidget(self.list_table)
        self.detail = QWidget()
        dl = QVBoxLayout(self.detail)
        self.header_title = QLabel("")
        self.header_title.setObjectName("pageTitle")
        dl.addWidget(self.header_title)
        cards_box, self.cards = ms.summary([
            ("status", "وضعیت", "info", "📌"), ("gross", "بهای تمام‌شده", "neutral", "🧾"),
            ("accum", "استهلاک انباشته", "warning", "📉"), ("nbv", "ارزش فعلی (دفتری)", "success", "✅"),
            ("location", "محل", "neutral", "📍"), ("cost_center", "مرکز هزینه", "neutral", "🏢"),
            ("custodian", "تحویل‌گیرنده", "neutral", "👤"), ("end_of_life", "پایان عمر", "neutral", "📅")])
        dl.addWidget(cards_box)
        self.actions = {}
        specs = (("capitalize", "سرمایه‌ای‌کردن", "fa_capitalize"), ("transfer", "انتقال", "fa_transfer"),
                 ("depreciate", "محاسبهٔ استهلاک", "fa_depreciation"), ("improve", "افزایش سرمایه / تعمیر", "fa_improve"),
                 ("impair", "کاهش ارزش", "fa_impair"), ("revalue", "تجدید ارزیابی", "fa_revalue"),
                 ("sell", "فروش", "fa_sell"), ("scrap", "اسقاط", "fa_scrap"), ("reclassify", "تغییر طبقه", "fa_reclassify"),
                 ("usage", "ثبت کارکرد", "fa_assets"), ("label", "برچسب QR", "fa_assets"), ("ledger", "دفتر دارایی", "fa_assets"))
        for i, (key, label, form) in enumerate(specs):
            b = QPushButton(label)
            b.setProperty("form", form)
            b.clicked.connect(lambda _c=False, k=key: self.action(k))
            self.actions[key] = b
        self.tabs = QTabWidget()
        self.t_overview = QLabel("")
        self.t_overview.setWordWrap(True)
        self.t_overview.setAlignment(Qt.AlignTop | Qt.AlignRight)
        self.t_financial = table(["جزء بها", "مبلغ", "مرجع"])
        self.t_fin_note = QLabel("")
        fin = QWidget()
        fl = QVBoxLayout(fin)
        fl.addWidget(self.t_fin_note)
        fl.addWidget(self.t_financial)
        self.t_depr = table(["دوره", "استهلاک", "ارزش دفتری", "وضعیت"])
        self.t_ledger = table(["تاریخ", "نوع", "بها", "استهلاک", "کاهش ارزش", "ارزش دفتری", "شرح"])
        self.t_transfers = table(["تاریخ", "تغییرات", "علت"])
        self.t_maint = table(["تاریخ", "نوع", "مبلغ", "شرح"])
        self.t_docs = table(["نوع", "فایل", "تاریخ"])
        docs = QWidget()
        dlay = QVBoxLayout(docs)
        drow = QHBoxLayout()
        self.doc_type = combo([(v, k) for k, v in fdocs.DOCUMENT_TYPES.items()])
        add_doc = QPushButton("افزودن مدرک")
        add_doc.clicked.connect(self.add_document)
        drow.addWidget(self.doc_type)
        drow.addWidget(add_doc)
        drow.addStretch(1)
        dlay.addLayout(drow)
        dlay.addWidget(self.t_docs)
        self.t_history = table(["تاریخ", "رویداد", "وضعیت", "مبلغ", "علت"])
        for widget, label in zip((self.t_overview, fin, self.t_depr, self.t_ledger, self.t_transfers, self.t_maint, docs,
                                  self.t_history), self.TABS):
            self.tabs.addTab(widget, label)
        dl.addWidget(self.tabs, stretch=1)
        split.addWidget(self.detail)
        split.setSizes([380, 820])
        # R275: جزئیاتِ دارایی کنارِ فهرست فقط با انتخابِ ردیف باز می‌شود؛ فهرست تمام‌عرض می‌ماند
        self.detail_drawer = FormDrawer(split, self.detail, open_signals=[self.list_table.clicked])
        outer.addWidget(split, stretch=1)
        A = self.actions
        outer.addWidget(ms.footer([
            [A["capitalize"], A["transfer"], A["reclassify"]],
            [A["depreciate"], A["usage"]],
            [A["improve"], A["impair"], A["revalue"]],
            [A["sell"], A["scrap"]],
            [A["label"], A["ledger"]]]))

    # --- بارگذاری ---------------------------------------------------------------------------------
    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        fac.ensure_default_categories(cid)
        self.lk = Lookups(cid)
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("— همهٔ طبقه‌ها —", None)
        for label, data in self.lk.categories:
            self.category_filter.addItem(P(label), data)
        self.category_filter.blockSignals(False)
        self.new_button.setEnabled(can(self.FORM, "CREATE"))
        self.reload_list()

    def reload_list(self) -> None:
        cid = company_id()
        if cid is None:
            return
        text = self.search.text().strip()
        found = fa.find_by_code(cid, text) if text.startswith("PEECHA-FA:") else None
        status = self.status_filter.currentData()
        rows = fa.list_assets(cid, category_id=self.category_filter.currentData(),
                              status=status if status not in (None, "ACTIVE") else None,
                              search=None if found else (text or None), include_closed=status != "ACTIVE")
        if found:
            rows = [r for r in rows if r.asset_id == found.asset_id]
        self._rows = rows
        show_cost = can("fa_cost_view", "VIEW")
        fill(self.list_table, [[r.asset_code, r.name, r.category_name, fac.STATUS_LABELS[r.status_code],
                                r.book_value if show_cost else "—"] for r in rows], [r.asset_id for r in rows])
        if rows and (self.asset is None or self.asset.asset_id not in {r.asset_id for r in rows}):
            self.list_table.selectRow(0)
        elif not rows:
            self.asset = None
            self._clear()

    def _selected(self) -> None:
        items = self.list_table.selectedItems()
        if items:
            asset_id = self.list_table.item(items[0].row(), 0).data(Qt.UserRole)
            self.load_asset(asset_id)

    def open_asset(self, asset_id: int) -> None:
        """از گزارش/داشبورد (دابل‌کلیک): فیلتر «همه» و همان دارایی."""
        self.status_filter.blockSignals(True)
        self.status_filter.setCurrentIndex(1)
        self.status_filter.blockSignals(False)
        self.search.clear()
        self.asset = None
        self.list_table.blockSignals(True)
        self.reload_list()
        self.list_table.clearSelection()
        for r in range(self.list_table.rowCount()):
            if self.list_table.item(r, 0).data(Qt.UserRole) == asset_id:
                self.list_table.selectRow(r)
                break
        self.list_table.blockSignals(False)
        self.load_asset(asset_id)
        self.detail_drawer.open()

    def _clear(self) -> None:
        self.header_title.setText("")
        for v in self.cards.values():
            v.setText("—")

    def load_asset(self, asset_id: int) -> None:
        cid = company_id()
        self.asset = a = fa.get_asset(cid, asset_id)
        lk = self.lk or Lookups(cid)
        name = dict((d, lb) for lb, d in lk.cost_centers)
        emp = dict((d, lb) for lb, d in lk.employees)
        show_cost = can("fa_cost_view", "VIEW")
        from peecha.db.base import new_session

        with new_session() as session:
            loc = fac.location_path(session, a.location_id)
        self.header_title.setText(P(f"{a.asset_code} -- {a.name}"))
        forecast = fd.forecast(cid, asset_id)
        values = {"status": "● " + fac.STATUS_LABELS[a.status_code], "gross": money(a.gross_cost) if show_cost else "—",
                  "accum": money(a.accumulated_depreciation + a.accumulated_impairment) if show_cost else "—",
                  "nbv": money(a.book_value) if show_cost else "—", "location": loc or "—",
                  "cost_center": name.get(a.cost_center_detail_account_id, "—"), "custodian": emp.get(a.custodian_employee_id, "—"),
                  "end_of_life": forecast[-1].period_code if forecast else "—"}
        for key, text in values.items():
            self.cards[key].setText(P(text))
        cat = next((lb for lb, d in lk.categories if d == a.category_id), "")
        overview = [f"طبقه: {cat}", f"نوع: {fac.TYPE_LABELS.get(a.asset_type_code, '')}",
                    f"برند/مدل/سریال: {a.brand or '-'} / {a.model or '-'} / {a.serial_no or '-'}",
                    f"منبع: {fa.SOURCE_LABELS.get(a.source_code, a.source_code)} -- فاکتور: {a.invoice_reference or '-'}",
                    f"تاریخ تحصیل: {numerals.format_jalali_date(a.acquisition_date) if a.acquisition_date else '-'}"
                    f" -- بهره‌برداری: {numerals.format_jalali_date(a.in_service_date) if a.in_service_date else '-'}",
                    f"روش استهلاک: {fac.METHOD_LABELS.get(a.depreciation_method)} -- عمر: {a.useful_life or '-'} "
                    f"({a.useful_life_unit}) — اسقاط: {money(a.residual_value) if show_cost else '—'}",
                    f"QR: {fa.qr_payload(a)}"]
        if a.is_production_machine:
            overview.append(f"تولید: مرکز کار {a.work_center_code or '-'} -- خط {a.production_line or '-'} "
                            f"-- ساعت استاندارد {a.standard_hours or '-'} -- کارکرد ثبت‌شده {a.units_consumed}")
        warranties = fp.warranties(asset_id)
        insurances = fp.insurances(asset_id)
        if warranties:
            overview.append("گارانتی تا " + numerals.format_jalali_date(warranties[-1].end_date))
        if insurances:
            overview.append("بیمه تا " + numerals.format_jalali_date(insurances[-1].end_date))
        children = fe.components(cid, asset_id)
        if children:
            overview.append("اجزا: " + "، ".join(f"{ch.asset_code} ({ch.name})" for ch in children))
        self.t_overview.setText(P("\n".join(overview)))
        if show_cost:
            fill(self.t_financial, [[fa.COST_TYPES.get(ci.cost_type, ci.cost_type), ci.amount, ci.reference or ""]
                                    for ci in fa.cost_items(asset_id)])
            self.t_fin_note.setText(P(f"بها {money(a.gross_cost)} -- استهلاک انباشته {money(a.accumulated_depreciation)} -- "
                                      f"کاهش ارزش {money(a.accumulated_impairment)} -- مازاد تجدید ارزیابی "
                                      f"{money(a.revaluation_surplus)}"))
        else:
            fill(self.t_financial, [])
            self.t_fin_note.setText("مشاهدهٔ ارقام بها نیازمند دسترسی «دارایی: مشاهدهٔ بها» است.")
        fill(self.t_depr, [[row.period_code, row.amount, row.book_value, "ثبت‌شده" if row.posted else "پیش‌بینی"]
                           for row in fd.schedule(cid, asset_id)])
        fill(self.t_ledger, [[t.date, t.label, t.cost, t.depreciation, t.impairment, t.book_value, t.description or ""]
                             for t in fa.ledger(cid, asset_id)])
        events = fa.events(cid, asset_id)
        fill(self.t_transfers, [[e.event_date, "، ".join(fa.TRANSFER_FIELDS.get(k, k) for k in (e.details or {})), e.reason or ""]
                                for e in events if e.event_type == "TRANSFER"])
        fill(self.t_maint, [[e.event_date, "افزایش سرمایه‌ای" if e.event_type == "IMPROVEMENT" else "تعمیر", e.amount, e.reason or ""]
                            for e in events if e.event_type in ("IMPROVEMENT", "MAINTENANCE")])
        fill(self.t_docs, [[fdocs.DOCUMENT_TYPES.get(d.document_type_code or "OTHER", ""), d.file_name, d.uploaded_at.date()]
                           for d in fdocs.list_documents(cid, asset_id)])
        labels = {"CAPITALIZATION": "سرمایه‌ای‌شدن", "TRANSFER": "انتقال", "RECLASS": "تغییر طبقه", "IMPROVEMENT": "بهسازی",
                  "MAINTENANCE": "تعمیر", "IMPAIRMENT": "کاهش ارزش", "REVALUATION": "تجدید ارزیابی", "SALE": "فروش",
                  "SCRAP": "اسقاط", "DONATION": "اهدا", "WRITE_OFF": "حذف", "SPLIT": "تقسیم", "MERGE": "ادغام", "STATUS": "وضعیت"}
        status_labels = {"POSTED": "ثبت‌شده", "PENDING_APPROVAL": "در انتظار تایید", "APPROVED": "تاییدشده", "REJECTED": "ردشده",
                         "DRAFT": "پیش‌نویس", "CANCELLED": "لغو"}
        fill(self.t_history, [[e.event_date, labels.get(e.event_type, e.event_type), status_labels.get(e.status_code, ""),
                               e.amount, e.reason or ""] for e in events])
        self._update_actions()

    def _update_actions(self) -> None:
        a = self.asset
        closed = a is None or a.status_code in fac.CLOSED_STATUSES
        for key, button in self.actions.items():
            form = button.property("form")
            action = "VIEW" if key in ("ledger", "label") else ("CREATE" if form != "fa_assets" else "EDIT")
            allowed = can(form, action) and a is not None
            if key in ("ledger", "label"):
                button.setEnabled(allowed)
            elif key == "capitalize":
                button.setEnabled(allowed and a.status_code in ("ACQUIRED", "UNDER_CONSTRUCTION"))
            else:
                button.setEnabled(allowed and not closed)

    # --- عملیات --------------------------------------------------------------------------------
    def new_asset(self):
        wizard = AssetWizard(self.lk or Lookups(company_id()), self)
        self.dialog_runner(wizard)
        if wizard.created_asset_id:
            self.reload_list()
            self.open_asset(wizard.created_asset_id)
        return wizard

    def _dialog(self, key: str) -> FormDialog | None:
        lk = self.lk or Lookups(company_id())
        a = self.asset
        if key == "capitalize":
            return FormDialog("سرمایه‌ای‌کردن", [("date", "تاریخ", date_field()), ("in_service_date", "تاریخ بهره‌برداری", date_field())],
                              "تاریخ شروع استهلاک طبق سیاست تنظیمات تعیین می‌شود.", self)
        if key == "transfer":
            loc, cc, emp = combo(lk.locations, "— بدون تغییر —"), combo(lk.cost_centers, "— بدون تغییر —"), combo(lk.employees, "— بدون تغییر —")
            br, dep = combo(lk.branches, "— بدون تغییر —"), combo(lk.departments, "— بدون تغییر —")
            return FormDialog("انتقال دارایی", [("date", "تاریخ", date_field()), ("location_id", "محل جدید", loc),
                                                 ("cost_center_detail_account_id", "مرکز هزینهٔ جدید", cc),
                                                 ("custodian_employee_id", "تحویل‌گیرندهٔ جدید", emp), ("branch_id", "شعبهٔ جدید", br),
                                                 ("department_id", "دپارتمان جدید", dep), ("reason", "علت", QLineEdit())], parent=self)
        if key == "improve":
            capital = QComboBox()
            capital.addItem("طبق سیاست (حد مبلغ)", None)
            capital.addItem("افزایش سرمایه‌ای", True)
            capital.addItem("هزینهٔ تعمیر", False)
            return FormDialog("افزایش سرمایه / تعمیر", [
                ("date", "تاریخ", date_field()), ("amount", "مبلغ", num_field()), ("offset_account_id", "حساب طرف مقابل",
                                                                                 combo(lk.accounts)),
                ("offset_detail_account_id", "طرف‌حساب", combo(lk.suppliers, "— بدون طرف‌حساب —")), ("capital", "نوع", capital),
                ("extend_life_months", "افزایش عمر (ماه)", num_field(0)), ("description", "شرح", QLineEdit())], parent=self)
        if key == "impair":
            return FormDialog("کاهش ارزش", [("date", "تاریخ", date_field()),
                                             ("recoverable_amount", "مبلغ بازیافتنی", num_field()), ("reason", "علت", QLineEdit())],
                              P(f"ارزش دفتری فعلی: {money(a.book_value)}"), self)
        if key == "revalue":
            return FormDialog("تجدید ارزیابی", [("date", "تاریخ", date_field()), ("new_value", "ارزش جدید", num_field()),
                                                 ("reason", "علت/کارشناس", QLineEdit())],
                              P(f"ارزش دفتری فعلی: {money(a.book_value)}"), self)
        if key == "sell":
            return FormDialog("فروش دارایی", [("date", "تاریخ", date_field()), ("price", "مبلغ فروش", num_field()),
                                               ("receivable_account_id", "حساب دریافتنی/بانک", combo(lk.accounts)),
                                               ("customer_detail_account_id", "خریدار", combo(lk.customers, "— خریدار —")),
                                               ("reason", "شرح", QLineEdit())],
                              P(f"ارزش دفتری: {money(a.book_value)} -- سود/زیان خودکار محاسبه می‌شود."), self)
        if key == "scrap":
            return FormDialog("اسقاط", [("date", "تاریخ", date_field()), ("reason", "علت", QLineEdit()),
                                        ("condition_note", "وضعیت فیزیکی", QLineEdit()), ("scrap_value", "ارزش ضایعات", num_field(0)),
                                        ("scrap_value_account_id", "حساب دریافت ضایعات", combo(lk.accounts, "— ندارد —"))],
                              P(f"ارزش دفتری: {money(a.book_value)}"), self)
        if key == "reclassify":
            return FormDialog("تغییر طبقه", [("new_category_id", "طبقهٔ جدید", combo(lk.categories)), ("date", "تاریخ", date_field()),
                                              ("reason", "علت", QLineEdit())], parent=self)
        if key == "usage":
            return FormDialog("ثبت کارکرد", [("date", "تاریخ", date_field()), ("units", "ساعت/واحد", num_field()),
                                              ("production_order_ref", "سفارش تولید", QLineEdit())], parent=self)
        return None

    def action(self, key: str):
        if self.asset is None:
            return None
        if key == "ledger":
            self.tabs.setCurrentIndex(3)
            return None
        if key == "depreciate":
            if self._main_window is not None:
                self._main_window.open_screen("FA_DEPRECIATION")
            return None
        if key == "label":
            return self.print_label()
        dlg = self._dialog(key)
        if dlg is None or not self.dialog_runner(dlg):
            return None
        return self.run_operation(key, dlg.values())

    def run_operation(self, key: str, v: dict):
        """اجرای عملیات با مقادیر فرم (برای دکمه‌ها و آزمون)؛ عملیات حساس از مسیر تایید می‌رود."""
        cid, uid, asset_id = company_id(), user_id(), self.asset.asset_id
        warnings = {"sell": "فروش دارایی سند حسابداری و سود/زیان ثبت می‌کند و برگشت‌پذیر نیست. ادامه می‌دهید؟",
                    "scrap": "اسقاط دارایی برگشت‌پذیر نیست. ادامه می‌دهید؟"}
        if key in warnings and not self.confirm(warnings[key]):
            return None
        try:
            if key == "capitalize":
                result = approval.request(cid, uid, "CAPITALIZE", asset_id, date=v["date"], in_service_date=v["in_service_date"])
            elif key == "transfer":
                targets = {k: v[k] for k in fa.TRANSFER_FIELDS if v.get(k) is not None}
                result = approval.request(cid, uid, "TRANSFER", asset_id, date=v["date"], reason=v.get("reason"), **targets)
            elif key == "improve":
                result = approval.request(cid, uid, "IMPROVE", asset_id, date=v["date"], amount=v["amount"],
                                          offset_account_id=v["offset_account_id"],
                                          offset_detail_account_id=v.get("offset_detail_account_id"),
                                          description=v.get("description"), capital=v.get("capital"),
                                          extend_life_months=int(v.get("extend_life_months") or 0))
            elif key == "impair":
                result = approval.request(cid, uid, "IMPAIR", asset_id, date=v["date"], recoverable_amount=v["recoverable_amount"],
                                          reason=v.get("reason") or "")
            elif key == "revalue":
                result = approval.request(cid, uid, "REVALUE", asset_id, date=v["date"], new_value=v["new_value"],
                                          reason=v.get("reason") or "")
            elif key == "sell":
                result = approval.request(cid, uid, "SELL", asset_id, date=v["date"], price=v["price"],
                                          receivable_account_id=v["receivable_account_id"],
                                          customer_detail_account_id=v.get("customer_detail_account_id"), reason=v.get("reason"))
            elif key == "scrap":
                result = approval.request(cid, uid, "SCRAP", asset_id, date=v["date"], reason=v.get("reason") or "",
                                          condition_note=v.get("condition_note"), scrap_value=v.get("scrap_value") or ZERO,
                                          scrap_value_account_id=v.get("scrap_value_account_id"))
            elif key == "reclassify":
                result = fa.reclassify(cid, uid, asset_id, v["new_category_id"], v["date"], v.get("reason"))
            elif key == "usage":
                result = fd.record_usage(cid, uid, asset_id, v["date"], v["units"], "PRODUCTION" if v.get("production_order_ref") else "MANUAL",
                                         v.get("production_order_ref"))
            else:
                return None
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return None
        pending = getattr(result, "status_code", None) == "PENDING_APPROVAL"
        theme.set_status_label(self.status_label, "درخواست به کارتابل تایید رفت." if pending else "انجام شد.", ok=True)
        self.reload_list()
        self.load_asset(asset_id)
        return result

    def print_label(self) -> QImage:
        image = asset_label_image(self.asset)
        path, _ = QFileDialog.getSaveFileName(self, "ذخیرهٔ برچسب QR", f"{self.asset.asset_code}.png", "PNG (*.png)") \
            if self.isVisible() else ("", "")
        if path:
            image.save(path)
        return image

    def add_document(self, file_path: str | None = None) -> int | None:
        if self.asset is None:
            return None
        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(self, "انتخاب مدرک")
        if not file_path:
            return None
        try:
            doc_id = fdocs.add_document(company_id(), user_id(), self.asset.asset_id, file_path, self.doc_type.currentData())
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return None
        self.load_asset(self.asset.asset_id)
        return doc_id


# =========================================================================================================
@ms.styled
class DepreciationScreen(QWidget):
    scroll_in_mdi = True
    FORM = "fa_depreciation"

    def __init__(self) -> None:
        super().__init__()
        self.confirm = lambda text: QMessageBox.question(self, "استهلاک", text) == QMessageBox.Yes
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("اجرای استهلاک دوره")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        hint = QLabel("محاسبه ← بررسی ← تایید ← ثبت. پس از ثبت، اصلاح فقط با «برگشت» (سند معکوس) ممکن است. "
                      "هزینهٔ استهلاک هر دارایی به مرکز هزینهٔ همان دارایی ثبت می‌شود.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        row = QHBoxLayout()
        self.period = QComboBox()
        today = datetime.date.today()
        for i in range(0, 25):
            code = fac.period_of(fac.add_months(today, -i))[0]
            self.period.addItem(P(code), code)
        row.addWidget(QLabel("دوره:"))
        row.addWidget(self.period)
        self.buttons = {}
        for key, label, action in (("calculate", "محاسبه", "CREATE"), ("review", "بررسی", "EDIT"), ("approve", "تایید", "APPROVE"),
                                   ("post", "ثبت", "CREATE"), ("reverse", "برگشت", "APPROVE")):
            b = QPushButton(label)
            b.setProperty("action", action)
            b.clicked.connect(lambda _c=False, k=key: self.do(k))
            row.addWidget(b)
            self.buttons[key] = b
        row.addStretch(1)
        outer.addLayout(row)
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)
        self.runs = table(["دوره", "وضعیت", "تعداد", "جمع استهلاک", "تاریخ ثبت"])
        self.runs.itemSelectionChanged.connect(self._show_lines)
        self.lines = table(["کد", "نام", "روش", "ارزش اول دوره", "استهلاک", "ارزش پایان دوره", "کارکرد"])
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.runs)
        split.addWidget(self.lines)
        outer.addWidget(split, stretch=1)
        self._runs = []

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self._runs = fd.list_runs(cid)
        fill(self.runs, [[r.period_code, fd.RUN_STATUS_LABELS[r.status_code], r.asset_count, r.total_amount, r.posting_date]
                         for r in self._runs], [r.run_id for r in self._runs])
        for b in self.buttons.values():
            b.setEnabled(can(self.FORM, b.property("action")))
        if self._runs:
            self.runs.selectRow(0)

    def _current_run(self):
        code = self.period.currentData()
        return next((r for r in self._runs if r.period_code == code and r.status_code != "REVERSED"), None)

    def _show_lines(self) -> None:
        items = self.runs.selectedItems()
        if not items:
            return
        run_id = self.runs.item(items[0].row(), 0).data(Qt.UserRole)
        fill(self.lines, [[ln.asset_code, ln.name, fac.METHOD_LABELS.get(ln.method, ln.method), ln.opening, ln.amount, ln.closing,
                           ln.units or ""] for ln in fd.run_lines(run_id)])

    def do(self, key: str) -> bool:
        cid, uid = company_id(), user_id()
        run = self._current_run()
        try:
            if key == "calculate":
                fd.calculate_run(cid, uid, self.period.currentData())
            elif run is None:
                raise ValueError("برای این دوره هنوز محاسبه‌ای انجام نشده است.")
            elif key == "review":
                fd.review_run(cid, uid, run.run_id)
            elif key == "approve":
                fd.approve_run(cid, uid, run.run_id)
            elif key == "post":
                if not self.confirm(P(f"استهلاک دورهٔ {run.period_code} به مبلغ {money(run.total_amount)} ثبت و سند حسابداری "
                                      "صادر می‌شود. ادامه می‌دهید؟")):
                    return False
                fd.post_run(cid, uid, run.run_id)
            elif key == "reverse":
                if not self.confirm("استهلاک این دوره با سند معکوس برگشت می‌خورد. ادامه می‌دهید؟"):
                    return False
                fd.reverse_run(cid, uid, run.run_id)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            self.refresh()
            return False
        theme.set_status_label(self.status_label, "انجام شد.", ok=True)
        self.refresh()
        return True


# =========================================================================================================
@ms.styled
class SetupScreen(QWidget):
    """طبقه‌ها (با حساب‌ها)، محل‌ها، گروه‌ها و سیاست‌ها."""

    scroll_in_mdi = True

    FORM = "fa_setup"

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("تنظیمات دارایی‌های ثابت")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, stretch=1)
        # طبقه‌ها
        cat = QWidget()
        cl = QHBoxLayout(cat)
        self.cat_table = table(["کد", "نام", "روش", "عمر (ماه)", "حساب‌ها"])
        self.cat_table.itemSelectionChanged.connect(self._cat_selected)
        cl.addWidget(self.cat_table, stretch=1)
        form_box = QWidget()
        self.cat_form = QFormLayout(form_box)
        self.cat_code, self.cat_name = QLineEdit(), QLineEdit()
        self.cat_method = combo([(v, k) for k, v in fac.METHOD_LABELS.items()])
        self.cat_life, self.cat_residual, self.cat_rate = num_field(), num_field(), num_field()
        self.cat_cc_required = QCheckBox("مرکز هزینه الزامی")
        self.cat_cc = QComboBox()
        self.cat_accounts = {k: QComboBox() for k in fac.ACCOUNT_FIELDS}
        for label, w in (("کد", self.cat_code), ("نام", self.cat_name), ("روش پیش‌فرض", self.cat_method),
                         ("عمر پیش‌فرض (ماه)", self.cat_life), ("درصد اسقاط", self.cat_residual), ("نرخ نزولی", self.cat_rate),
                         ("", self.cat_cc_required), ("مرکز هزینهٔ پیش‌فرض", self.cat_cc)):
            self.cat_form.addRow(label, w)
        for k, label in fac.ACCOUNT_FIELDS.items():
            self.cat_form.addRow(label, self.cat_accounts[k])
        brow = QHBoxLayout()
        self.cat_new, self.cat_save = QPushButton("طبقهٔ جدید"), QPushButton("ذخیره")
        self.cat_save.setObjectName("primaryButton")
        self.cat_new.clicked.connect(self._cat_clear)
        self.cat_save.clicked.connect(self.save_category)
        # R276: حذفِ طبقه (اگر در دارایی‌ها استفاده شده باشد غیرفعال می‌شود)
        self.cat_delete = delete_button("حذف طبقهٔ انتخاب‌شده")
        self.cat_delete.clicked.connect(lambda: confirm_and_delete(
            self, "طبقهٔ دارایی", self.cat_name.text(), fam.AssetCategory, self._cat_id, company_id(), self.refresh))
        brow.addWidget(self.cat_new)
        brow.addWidget(self.cat_save)
        brow.addWidget(self.cat_delete)
        self.cat_form.addRow(brow)
        cl.addWidget(form_box, stretch=1)
        # R275: فرمِ طبقه کنارِ فهرست فقط با کلیکِ ردیف یا «جدید» باز می‌شود
        self.cat_drawer = FormDrawer(cl, form_box, open_signals=[self.cat_table.clicked], on_new=self._cat_clear,
                                     new_tooltip="طبقهٔ جدید")
        self.tabs.addTab(cat, "طبقه‌ها و حساب‌ها")
        # محل‌ها
        loc = QWidget()
        ll = QVBoxLayout(loc)
        self.loc_table = table(["کد", "نام", "نوع", "مسیر"])
        # R276: انتخابِ ردیف برایِ ویرایش/حذف
        self.loc_table.itemSelectionChanged.connect(self._loc_selected)
        ll.addWidget(self.loc_table)
        lrow = QHBoxLayout()
        self.loc_code, self.loc_name = QLineEdit(), QLineEdit()
        self.loc_type = combo([("سایت/کارخانه", "SITE"), ("ساختمان", "BUILDING"), ("طبقه", "FLOOR"), ("اتاق", "ROOM"),
                               ("خط تولید", "LINE"), ("سایر", "OTHER")])
        self.loc_parent = QComboBox()
        add_loc = QPushButton("ذخیرهٔ محل")
        add_loc.clicked.connect(self.save_location)
        new_loc = QPushButton("محل جدید")
        new_loc.clicked.connect(self._loc_clear)
        del_loc = delete_button("حذف محل انتخاب‌شده")
        del_loc.clicked.connect(lambda: confirm_and_delete(
            self, "محل دارایی", self.loc_name.text(), fam.AssetLocation, self._loc_id, company_id(), self.refresh))
        for w in (QLabel("کد"), self.loc_code, QLabel("نام"), self.loc_name, self.loc_type, QLabel("زیر"), self.loc_parent, add_loc,
                  new_loc, del_loc):
            lrow.addWidget(w)
        ll.addLayout(lrow)
        self.tabs.addTab(loc, "محل‌ها")
        # گروه‌ها
        grp = QWidget()
        gl = QVBoxLayout(grp)
        self.grp_table = table(["کد", "نام"])
        self.grp_table.itemSelectionChanged.connect(self._grp_selected)
        gl.addWidget(self.grp_table)
        grow = QHBoxLayout()
        self.grp_code, self.grp_name = QLineEdit(), QLineEdit()
        add_grp = QPushButton("ذخیرهٔ گروه")
        add_grp.clicked.connect(self.save_group)
        new_grp = QPushButton("گروه جدید")
        new_grp.clicked.connect(self._grp_clear)
        del_grp = delete_button("حذف گروه انتخاب‌شده")
        del_grp.clicked.connect(lambda: confirm_and_delete(
            self, "گروه دارایی", self.grp_name.text(), fam.AssetGroup, self._grp_id, company_id(), self.refresh))
        for w in (QLabel("کد"), self.grp_code, QLabel("نام"), self.grp_name, add_grp, new_grp, del_grp):
            grow.addWidget(w)
        gl.addLayout(grow)
        self.tabs.addTab(grp, "گروه‌ها")
        # سیاست‌ها
        pol = QWidget()
        pf = QFormLayout(pol)
        self.start_rule = combo([("تاریخ بهره‌برداری", "IN_SERVICE"), ("تاریخ تحصیل", "ACQUISITION"), ("ماه بعد", "NEXT_MONTH"),
                                 ("تاریخ مشخص (در سرمایه‌ای‌کردن)", "SPECIFIC")])
        self.improve_min, self.large_improve = num_field(), num_field()
        self.require_cc = QCheckBox("مرکز هزینه برای همهٔ دارایی‌ها الزامی")
        save_pol = QPushButton("ذخیرهٔ سیاست‌ها")
        save_pol.setObjectName("primaryButton")
        save_pol.clicked.connect(self.save_settings)
        for label, w in (("شروع استهلاک", self.start_rule), ("حد سرمایه‌ای‌شدن بهسازی", self.improve_min),
                         ("حد بهسازی نیازمند تایید", self.large_improve), ("", self.require_cc), ("", save_pol)):
            pf.addRow(label, w)
        self.tabs.addTab(pol, "سیاست‌ها")
        self._cat_id = None
        self._cats = []
        self._loc_id = self._grp_id = None
        self._locs, self._grps = [], []

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        fac.ensure_default_categories(cid)
        lk = Lookups(cid)
        for box in self.cat_accounts.values():
            box.clear()
            box.addItem("— تعیین نشده —", None)
            for label, data in lk.accounts:
                box.addItem(P(label), data)
        self.cat_cc.clear()
        self.cat_cc.addItem("— ندارد —", None)
        for label, data in lk.cost_centers:
            self.cat_cc.addItem(P(label), data)
        self._cats = fac.list_categories(cid)
        fill(self.cat_table, [[c.code, c.name, fac.METHOD_LABELS[c.default_method], c.default_life_months or "",
                               "کامل" if not fac.missing_accounts(c, tuple(fac.ACCOUNT_FIELDS)[:3]) else "ناقص"]
                              for c in self._cats], [c.category_id for c in self._cats])
        locs = fac.list_locations(cid)
        from peecha.db.base import new_session

        with new_session() as session:
            paths = {loc.location_id: fac.location_path(session, loc.location_id) for loc in locs}
        types = {"SITE": "سایت", "BUILDING": "ساختمان", "FLOOR": "طبقه", "ROOM": "اتاق", "LINE": "خط تولید", "OTHER": "سایر"}
        self._locs = locs
        fill(self.loc_table, [[loc.code, loc.name, types.get(loc.location_type, ""), paths[loc.location_id]] for loc in locs],
             [loc.location_id for loc in locs])
        self.loc_parent.clear()
        self.loc_parent.addItem("— ریشه —", None)
        for loc in locs:
            self.loc_parent.addItem(P(f"{loc.code} — {loc.name}"), loc.location_id)
        self._grps = fac.list_groups(cid)
        fill(self.grp_table, [[g.code, g.name] for g in self._grps], [g.group_id for g in self._grps])
        self._loc_clear()
        self._grp_clear()
        s = fac.get_settings(cid)
        set_combo(self.start_rule, s.depreciation_start_rule)
        self.improve_min.setText(decimals.plain(s.improvement_capitalize_min))
        self.large_improve.setText(decimals.plain(s.large_improvement_approval_min) if s.large_improvement_approval_min else "")
        self.require_cc.setChecked(s.require_cost_center)
        allowed = can(self.FORM, "EDIT")
        for b in self.findChildren(QPushButton):
            b.setEnabled(allowed)

    def _loc_clear(self) -> None:
        self._loc_id = None
        self.loc_code.clear()
        self.loc_name.clear()

    def _loc_selected(self) -> None:
        loc_id = selected_data(self.loc_table)
        loc = next((x for x in self._locs if x.location_id == loc_id), None)
        if loc is None:
            return
        self._loc_id = loc_id
        self.loc_code.setText(loc.code)
        self.loc_name.setText(loc.name)
        set_combo(self.loc_type, loc.location_type)
        set_combo(self.loc_parent, loc.parent_location_id)

    def _grp_clear(self) -> None:
        self._grp_id = None
        self.grp_code.clear()
        self.grp_name.clear()

    def _grp_selected(self) -> None:
        grp_id = selected_data(self.grp_table)
        grp = next((x for x in self._grps if x.group_id == grp_id), None)
        if grp is None:
            return
        self._grp_id = grp_id
        self.grp_code.setText(grp.code)
        self.grp_name.setText(grp.name)

    def _cat_clear(self) -> None:
        self._cat_id = None
        for w in (self.cat_code, self.cat_name, self.cat_life, self.cat_residual, self.cat_rate):
            w.clear()
        for box in self.cat_accounts.values():
            box.setCurrentIndex(0)

    def _cat_selected(self) -> None:
        items = self.cat_table.selectedItems()
        if not items:
            return
        cat_id = self.cat_table.item(items[0].row(), 0).data(Qt.UserRole)
        c = next(x for x in self._cats if x.category_id == cat_id)
        self._cat_id = cat_id
        self.cat_code.setText(c.code)
        self.cat_name.setText(c.name)
        set_combo(self.cat_method, c.default_method)
        self.cat_life.setText(P(c.default_life_months or ""))
        self.cat_residual.setText(decimals.plain(c.default_residual_percent))
        self.cat_rate.setText(decimals.plain(c.default_declining_rate) if c.default_declining_rate else "")
        self.cat_cc_required.setChecked(c.cost_center_required)
        set_combo(self.cat_cc, c.default_cost_center_detail_account_id)
        for k, box in self.cat_accounts.items():
            set_combo(box, getattr(c, k))

    def save_category(self) -> bool:
        try:
            fac.save_category(company_id(), fac.CategoryFields(
                self.cat_code.text(), self.cat_name.text(), self.cat_method.currentData(), int(dec(self.cat_life.text())) or None,
                dec(self.cat_residual.text()), dec(self.cat_rate.text()) or None, self.cat_cc_required.isChecked(),
                self.cat_cc.currentData(), {k: b.currentData() for k, b in self.cat_accounts.items()}),
                category_id=self._cat_id, user_id=user_id())
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return False
        theme.set_status_label(self.status_label, "طبقه ذخیره شد.", ok=True)
        self.refresh()
        return True

    def save_location(self) -> bool:
        try:
            fac.save_location(company_id(), self.loc_code.text(), self.loc_name.text(), self.loc_type.currentData(),
                              self.loc_parent.currentData(), location_id=self._loc_id)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return False
        self.loc_code.clear()
        self.loc_name.clear()
        self.refresh()
        return True

    def save_group(self) -> bool:
        try:
            fac.save_group(company_id(), self.grp_code.text(), self.grp_name.text(), self._grp_id)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return False
        self.refresh()
        return True

    def save_settings(self) -> None:
        fac.update_settings(company_id(), user_id(), depreciation_start_rule=self.start_rule.currentData(),
                            improvement_capitalize_min=dec(self.improve_min.text()),
                            large_improvement_approval_min=dec(self.large_improve.text()) or None,
                            require_cost_center=self.require_cc.isChecked())
        theme.set_status_label(self.status_label, "سیاست‌ها ذخیره شد.", ok=True)


# =========================================================================================================
@ms.styled
class CipScreen(QWidget):
    scroll_in_mdi = True
    FORM = "fa_cip"

    def __init__(self) -> None:
        super().__init__()
        self.dialog_runner = lambda dlg: dlg.exec() == QDialog.Accepted
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("دارایی در جریان تکمیل (CIP)")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        hint = QLabel("هزینه‌های ساخت (مواد از انبار، دستمزد، نصب، حمل، مهندسی) جمع و در پایان به دارایی تبدیل می‌شود.")
        hint.setObjectName("sectionHint")
        outer.addWidget(hint)
        row = QHBoxLayout()
        self.buttons = {}
        for key, label in (("new", "پروژهٔ جدید"), ("cost", "ثبت هزینه"), ("material", "مصرف مواد از انبار"),
                           ("capitalize", "تبدیل به دارایی")):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, k=key: self.action(k))
            row.addWidget(b)
            self.buttons[key] = b
        row.addStretch(1)
        outer.addLayout(row)
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)
        self.projects = table(["کد", "نام", "شروع", "وضعیت", "جمع هزینه"])
        outer.addWidget(self.projects, stretch=1)
        self._rows = []

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self._rows = fe.list_cip(cid)
        status = {"OPEN": "در جریان", "CAPITALIZED": "سرمایه‌ای‌شده", "CANCELLED": "لغو"}
        fill(self.projects, [[p.code, p.name, p.start_date, status[p.status], p.total] for p in self._rows],
             [p.cip_id for p in self._rows])
        for b in self.buttons.values():
            b.setEnabled(can(self.FORM, "CREATE"))

    def _selected(self):
        items = self.projects.selectedItems()
        return self.projects.item(items[0].row(), 0).data(Qt.UserRole) if items else None

    def action(self, key: str, values: dict | None = None):
        from peecha.services import inventory_catalog as catalog_service
        from peecha.services import inventory_locations as locations_service

        cid, uid = company_id(), user_id()
        lk = Lookups(cid)
        cip_id = self._selected()
        if key != "new" and cip_id is None:
            theme.set_status_label(self.status_label, "یک پروژه انتخاب کنید.", ok=False)
            return None
        if values is None:
            if key == "new":
                dlg = FormDialog("پروژهٔ جدید", [("code", "کد", QLineEdit()), ("name", "نام", QLineEdit()),
                                                 ("category_id", "طبقهٔ دارایی نهایی", combo(lk.categories)),
                                                 ("start_date", "تاریخ شروع", date_field()),
                                                 ("cost_center", "مرکز هزینه", combo(lk.cost_centers, "— ندارد —")),
                                                 ("project", "پروژه", combo(lk.projects, "— ندارد —"))], parent=self)
            elif key == "cost":
                dlg = FormDialog("ثبت هزینه", [("date", "تاریخ", date_field()),
                                                ("cost_type", "نوع", combo([(v, k) for k, v in fe.CIP_COST_TYPES.items() if k != "MATERIAL"])),
                                                ("amount", "مبلغ", num_field()), ("offset_account_id", "حساب طرف مقابل", combo(lk.accounts)),
                                                ("description", "شرح", QLineEdit())], parent=self)
            elif key == "material":
                items = [(f"{i.code} — {i.name or ''}", i.item_id) for i in catalog_service.list_items(cid, transactable_only=True)]
                whs = [(f"{w.code} — {w.name}", w.warehouse_id) for w in locations_service.list_warehouses(cid, active_only=True)]
                dlg = FormDialog("مصرف مواد", [("date", "تاریخ", date_field()), ("item_id", "کالا", combo(items)),
                                                ("warehouse_id", "انبار", combo(whs)), ("quantity", "مقدار (واحد پایه)", num_field())],
                                 "خروج از انبار با موتور انبار و بهای واقعی خروج.", self)
            else:
                dlg = FormDialog("تبدیل به دارایی", [("asset_code", "کد دارایی", QLineEdit()), ("name", "نام", QLineEdit()),
                                                     ("date", "تاریخ سرمایه‌ای‌شدن", date_field()),
                                                     ("in_service_date", "تاریخ بهره‌برداری", date_field())], parent=self)
            if not self.dialog_runner(dlg):
                return None
            values = dlg.values()
        try:
            if key == "new":
                result = fe.create_cip(cid, uid, values["code"] or "", values["name"] or "", values["category_id"],
                                       values["start_date"], values.get("cost_center"), values.get("project"))
            elif key == "cost":
                result = fe.add_cip_cost(cid, uid, cip_id, values["date"], values["cost_type"], values["amount"],
                                         values["offset_account_id"], description=values.get("description"))
            elif key == "material":
                from peecha.db.base import new_session
                from peecha.db.models.inventory import Item

                with new_session() as session:
                    uom = session.get(Item, values["item_id"]).base_uom_id
                result = fe.add_cip_material(cid, uid, cip_id, values["date"], values["item_id"], values["warehouse_id"],
                                             values["quantity"], uom)
            else:
                project = next(p for p in self._rows if p.cip_id == cip_id)
                result = fe.capitalize_cip(cid, uid, cip_id, values["date"], fa.AssetFields(
                    asset_code=values["asset_code"] or "", name=values["name"] or "", category_id=project.category_id),
                    in_service_date=values.get("in_service_date"))
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return None
        theme.set_status_label(self.status_label, "انجام شد.", ok=True)
        self.refresh()
        return result


# =========================================================================================================
@ms.styled
class PhysicalCountScreen(QWidget):
    scroll_in_mdi = True
    FORM = "fa_physical_count"

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("شمارش فیزیکی دارایی")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        row = QHBoxLayout()
        self.count_combo = QComboBox()
        self.count_combo.currentIndexChanged.connect(self._load_items)
        self.code, self.location = QLineEdit(), QComboBox()
        self.code.setPlaceholderText("کد شمارش جدید")
        new = QPushButton("شمارش جدید")
        new.clicked.connect(self.new_count)
        for w in (QLabel("شمارش:"), self.count_combo, self.code, QLabel("محل:"), self.location, new):
            row.addWidget(w)
        row.addStretch(1)
        outer.addLayout(row)
        scan_row = QHBoxLayout()
        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText("اسکن QR/بارکد یا تایپ کد دارایی + Enter")
        self.scan_input.returnPressed.connect(lambda: self.scan())
        self.found_location = QComboBox()
        self.damaged = QCheckBox("آسیب‌دیده")
        self.apply_moves = QCheckBox("ثبت محل یافت‌شده در شناسنامه")
        close = QPushButton("بستن شمارش")
        close.clicked.connect(self.close_count)
        for w in (self.scan_input, QLabel("محل یافت:"), self.found_location, self.damaged, self.apply_moves, close):
            scan_row.addWidget(w)
        outer.addLayout(scan_row)
        self.status_label = QLabel("")
        outer.addWidget(self.status_label)
        self.items = table(["کد", "نام", "نتیجه", "محل مورد انتظار", "محل یافت‌شده", "روش"])
        outer.addWidget(self.items, stretch=1)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        locs = fac.list_locations(cid)
        for box, none in ((self.location, "— همهٔ محل‌ها —"), (self.found_location, "— محل شمارش —")):
            box.clear()
            box.addItem(none, None)
            for loc in locs:
                box.addItem(P(f"{loc.code} — {loc.name}"), loc.location_id)
        self.count_combo.blockSignals(True)
        self.count_combo.clear()
        for cnt in fp.list_counts(cid):
            self.count_combo.addItem(P(f"{cnt.code} ({'باز' if cnt.status_code == 'OPEN' else 'بسته'})"), cnt.count_id)
        self.count_combo.blockSignals(False)
        self._load_items()

    def _load_items(self) -> None:
        count_id = self.count_combo.currentData()
        rows = fp.count_items(company_id(), count_id) if count_id else []
        fill(self.items, [[i.asset_code, i.name, i.label, i.expected_location, i.found_location, i.method or ""] for i in rows])

    def new_count(self) -> int | None:
        try:
            count_id = fp.create_count(company_id(), user_id(), self.code.text().strip() or f"CNT-{datetime.datetime.now():%y%m%d%H%M}",
                                       datetime.date.today(), self.location.currentData())
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return None
        self.refresh()
        self.count_combo.setCurrentIndex(self.count_combo.findData(count_id))
        return count_id

    def scan(self, code: str | None = None):
        count_id = self.count_combo.currentData()
        code = code if code is not None else self.scan_input.text().strip()
        if not count_id or not code:
            return None
        method = "QR" if code.startswith("PEECHA-FA:") else "BARCODE"
        try:
            res = fp.scan(company_id(), count_id, code, self.found_location.currentData(), damaged=self.damaged.isChecked(),
                          method=method)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return None
        theme.set_status_label(self.status_label, P(f"{res.asset_code}: {res.label}"), ok=res.result == "FOUND")
        self.scan_input.clear()
        self.damaged.setChecked(False)
        self._load_items()
        return res

    def close_count(self):
        count_id = self.count_combo.currentData()
        if not count_id:
            return None
        try:
            summary = fp.close_count(company_id(), user_id(), count_id, self.apply_moves.isChecked())
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return None
        theme.set_status_label(self.status_label, P("شمارش بسته شد: " + "، ".join(
            f"{fp.RESULT_LABELS[k]} {v}" for k, v in summary.items())), ok=True)
        self.refresh()
        return summary
