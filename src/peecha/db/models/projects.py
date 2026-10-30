"""R363: پروژه‌ها، فاز و فعالیت، پیوند فعالیت‌ها، پیشرفت، خط مبنا و نمودار گانت."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services import hr as hr_service
from peecha.services.projects import core as prj
from peecha.services.projects import costs as prj_costs
from peecha.services.projects import schedule as sch
from peecha.ui import report_export, theme
from peecha.ui.project_gantt import ZOOMS, GanttChart
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, money, selected_data, set_combo, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header

_TASK_HEADERS = ["شماره", "فعالیت", "مدت (روز کاری)", "شروع", "پایان", "پیش‌نیازها", "شناوری", "پیشرفت", "مسئول", "وضعیت"]
_PROJECT_HEADERS = ["کد", "نام پروژه", "کارفرما", "مدیر پروژه", "وضعیت", "شروع", "پایان هدف", "فعالیت‌ها", "مبلغ قرارداد"]


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _bar(*buttons) -> QHBoxLayout:
    row = QHBoxLayout()
    for label, glyph, kind, slot in buttons:
        button = _btn(label, glyph, kind)
        button.clicked.connect(slot)
        row.addWidget(button)
    row.addStretch(1)
    return row


def _ltr(text: str) -> str:
    """پیش‌نیاز مثل 1.1SS+1 در متن راست‌به‌چپ به‌هم نریزد."""
    return "\u2066" + text + "\u2069"


def _pct(value: decimal.Decimal) -> str:
    return P(f"{value.normalize():f}٪")


class ProjectsScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.projects: list = []
        self.project_id: int | None = None
        self.schedule = None
        self.links: list = []
        self._task_id: int | None = None
        self.confirm = None  # برای آزمون: تابعی که پاسخ پرسش تایید را برمی‌گرداند
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "پروژه‌ها و زمان‌بندی", "هر پروژه روی همان تفصیلی «پروژه» است که اسناد مالی، خرید و انبار به آن برچسب می‌خورند. فاز و فعالیت "
            "و پیوند میان فعالیت‌ها را تعریف کنید؛ تاریخ‌ها با روزهای کاری و تعطیلات شرکت محاسبه و مسیر بحرانی مشخص می‌شود."))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._projects_tab(), "پروژه‌ها")
        self.tabs.addTab(self._tasks_tab(), "فاز و فعالیت")
        self.tabs.addTab(self._gantt_tab(), "نمودار گانت")
        self.tabs.addTab(self._cost_tab(), "هزینه و کارکرد")
        from peecha.ui.screens.project_billing import ProjectBillingTab  # R365

        self.billing_tab = ProjectBillingTab(self._status)
        self.tabs.addTab(self.billing_tab, "فهرست بها و صورت‌وضعیت")
        from peecha.ui.screens.project_changes import ProjectChangesTab  # R366

        self.changes_tab = ProjectChangesTab(self._status)
        self.changes_tab.on_decided = self._reload_project
        self.tabs.addTab(self.changes_tab, "درخواست تغییر")
        layout.addWidget(self.tabs, 1)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    # --- پروژه‌ها --------------------------------------------------------------------------------------------------------
    def _projects_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.project_table = table(_PROJECT_HEADERS)
        self.project_table.itemSelectionChanged.connect(self._load_project)
        v.addWidget(self.project_table, 1)
        self.detail_combo = combo([], "— پروژهٔ جدید —")
        self.detail_combo.currentIndexChanged.connect(self._detail_changed)
        self.code_field, self.name_field = QLineEdit(), QLineEdit()
        self.customer_combo, self.manager_combo = combo([], "—"), combo([], "—")
        self.status_combo = QComboBox()
        for code, label in prj.STATUSES.items():
            self.status_combo.addItem(label, code)
        self.start_field = JalaliDateEdit()
        self.target_field = JalaliDateEdit(allow_empty=True)
        self.contract_field = QLineEdit()
        self.contract_field.setPlaceholderText("۰")
        self.description_field = QLineEdit()
        v.addWidget(FieldGrid([
            FieldSpec("prj_detail", "تفصیلی پروژه", self.detail_combo, span=1),
            FieldSpec("prj_code", "کد", self.code_field, span=1), FieldSpec("prj_name", "نام پروژه", self.name_field, span=1),
            FieldSpec("prj_customer", "کارفرما", self.customer_combo, span=1),
            FieldSpec("prj_manager", "مدیر پروژه", self.manager_combo, span=1), FieldSpec("prj_status", "وضعیت", self.status_combo, span=1),
            FieldSpec("prj_start", "شروع", self.start_field, span=1), FieldSpec("prj_target", "پایان هدف", self.target_field, span=1),
            FieldSpec("prj_contract", "مبلغ قرارداد", self.contract_field, span=1),
            FieldSpec("prj_desc", "شرح", self.description_field, span=3),
        ]))
        bar = _bar(("ذخیرهٔ پروژه", "💾", "primary", self.save_project), ("پروژهٔ جدید", "🆕", "", self.new_project),
                   ("حذف پروژه", "🗑️", "danger", self.delete_project), ("به‌روزرسانی", "🔄", "", self.refresh))
        from peecha.ui.screens.dms_related import related_documents_button  # R366

        self.related_documents_button = related_documents_button(self, "project", lambda: self.project_id)
        bar.insertWidget(bar.count() - 1, self.related_documents_button)
        v.addLayout(bar)
        return w

    def _detail_changed(self) -> None:
        free = self.detail_combo.currentData() is None and self.project_id is None
        self.code_field.setEnabled(free)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        from peecha.services import detail_dimensions as dims

        employees = [(f"{e.employee_code} — {e.full_name}", e.employee_id) for e in hr_service.list_employees(cid) if e.status == "ACTIVE"]
        for box, items in ((self.customer_combo, [(f"{c['code']} — {c['name'] or ''}", c["detail_account_id"]) for c in dims.list_customers(cid)]),
                           (self.manager_combo, employees), (self.responsible_combo, employees)):
            current = box.currentData()
            box.clear()
            box.addItem("—", None)
            for label, data in items:
                box.addItem(P(label), data)
            set_combo(box, current)
        self.detail_combo.blockSignals(True)
        self.detail_combo.clear()
        self.detail_combo.addItem("— پروژهٔ جدید —", None)
        for label, data in prj.free_project_details(cid):
            self.detail_combo.addItem(P(label), data)
        self.detail_combo.blockSignals(False)
        self.projects = prj.list_projects(cid)
        fill(self.project_table, [[p.code, p.name, p.customer or "—", p.manager or "—", p.status_label, p.start_date,
                                   p.target_end_date or "—", p.task_count, p.contract_amount] for p in self.projects],
             [p.project_id for p in self.projects])
        if self.project_id is not None:
            row = next((i for i, p in enumerate(self.projects) if p.project_id == self.project_id), None)
            if row is not None:
                self.project_table.blockSignals(True)
                self.project_table.setCurrentCell(row, 0)
                self.project_table.blockSignals(False)
            self.load_schedule()

    def _load_project(self) -> None:
        pid = selected_data(self.project_table)
        p = next((x for x in self.projects if x.project_id == pid), None)
        if p is None:
            return
        self.project_id = p.project_id
        self.detail_combo.setCurrentIndex(0)
        self.detail_combo.setEnabled(False)
        self.code_field.setText(p.code)
        self.code_field.setEnabled(False)
        self.name_field.setText(p.name)
        set_combo(self.customer_combo, p.customer_detail_account_id)
        set_combo(self.manager_combo, p.manager_employee_id)
        self.status_combo.setCurrentIndex(self.status_combo.findData(p.status_code))
        self.start_field.setDate(p.start_date)
        self.target_field.setDate(p.target_end_date)
        self.contract_field.setText(P(f"{p.contract_amount.normalize():f}") if p.contract_amount else "")
        self.description_field.setText(p.description)
        self.load_schedule()

    def _reload_project(self) -> None:
        self.refresh()
        self._load_project()

    def open_project(self, project_id: int, tab: str | None = None) -> None:
        """باز کردن یک پروژه از سبد پروژه‌ها یا کارتابل (tab = "changes" برای درخواست تغییر)."""
        self.refresh()
        row = next((i for i, p in enumerate(self.projects) if p.project_id == project_id), None)
        if row is None:
            return
        self.project_table.setCurrentCell(row, 0)
        self.project_id = project_id
        self._load_project()
        self.tabs.setCurrentWidget(self.changes_tab if tab == "changes" else self.tabs.widget(1))

    def new_project(self) -> None:
        self.project_id = None
        self.project_table.clearSelection()
        self.detail_combo.setEnabled(True)
        self.detail_combo.setCurrentIndex(0)
        for field in (self.code_field, self.name_field, self.contract_field, self.description_field):
            field.clear()
        self.code_field.setEnabled(True)
        set_combo(self.customer_combo, None)
        set_combo(self.manager_combo, None)
        self.status_combo.setCurrentIndex(0)
        self.start_field.setDate(datetime.date.today())
        self.target_field.setDate(None)
        self.load_schedule()

    def _project_fields(self) -> prj.ProjectFields:
        return prj.ProjectFields(
            start_date=self.start_field.date(), project_detail_account_id=self.detail_combo.currentData() if self.project_id is None else None,
            code=self.code_field.text(), name=self.name_field.text(), customer_detail_account_id=self.customer_combo.currentData(),
            manager_employee_id=self.manager_combo.currentData(), target_end_date=self.target_field.date(),
            contract_amount=dec(self.contract_field.text()), description=self.description_field.text(),
            status_code=self.status_combo.currentData())

    def save_project(self) -> int | None:
        try:
            self.project_id = prj.save_project(company_id(), user_id(), self._project_fields(), self.project_id)
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "مبلغ قرارداد نامعتبر است.", False)
            return None
        self.refresh()
        self._load_project()
        self._status("پروژه ذخیره شد.", True)
        return self.project_id

    def delete_project(self) -> bool:
        if self.project_id is None:
            self._status("یک پروژه را انتخاب کنید.", False)
            return False
        if not (self.confirm() if self.confirm else QMessageBox.question(
                self, "حذف پروژه", "پروژه و همهٔ فعالیت‌هایش حذف شود؟ تفصیلی پروژه و اسناد آن سر جایشان می‌مانند.") == QMessageBox.Yes):
            return False
        try:
            prj.delete_project(company_id(), self.project_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.new_project()
        self.refresh()
        self._status("پروژه حذف شد.", True)
        return True

    # --- فاز و فعالیت ----------------------------------------------------------------------------------------------------
    def _tasks_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.summary_label = QLabel("ابتدا یک پروژه را در زبانهٔ «پروژه‌ها» انتخاب کنید.")
        self.summary_label.setWordWrap(True)
        v.addWidget(self.summary_label)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(_TASK_HEADERS)
        self.tree.setLayoutDirection(Qt.RightToLeft)
        self.tree.itemSelectionChanged.connect(self._load_task)
        v.addWidget(self.tree, 1)
        self.task_name_field = QLineEdit()
        self.parent_combo = combo([], "— بدون فاز —")
        self.duration_field = QSpinBox()
        self.duration_field.setRange(0, 3650)
        self.duration_field.setValue(1)
        self.sne_field = JalaliDateEdit(allow_empty=True)
        self.responsible_combo = combo([], "—")
        self.hours_field = QDoubleSpinBox()
        self.hours_field.setRange(0, 1_000_000)
        self.cost_field = QLineEdit()
        self.cost_field.setPlaceholderText("۰")
        self.task_notes_field = QLineEdit()
        v.addWidget(FieldGrid([
            FieldSpec("task_name", "نام فعالیت یا فاز", self.task_name_field, span=1),
            FieldSpec("task_parent", "زیرمجموعهٔ فاز", self.parent_combo, span=1),
            FieldSpec("task_duration", "مدت (روز کاری، صفر = نقطهٔ عطف)", self.duration_field, span=1),
            FieldSpec("task_sne", "شروع نه زودتر از", self.sne_field, span=1),
            FieldSpec("task_owner", "مسئول", self.responsible_combo, span=1),
            FieldSpec("task_hours", "ساعت برنامه‌ای", self.hours_field, span=1),
            FieldSpec("task_cost", "هزینهٔ برنامه‌ای", self.cost_field, span=1),
            FieldSpec("task_notes", "توضیح", self.task_notes_field, span=2),
        ]))
        v.addLayout(_bar(("ذخیرهٔ فعالیت", "💾", "primary", self.save_task), ("فعالیت جدید", "🆕", "", self.new_task),
                         ("حذف فعالیت", "🗑️", "danger", self.delete_task), ("بالا بردن", "⬆️", "", lambda: self.move_task(-1)),
                         ("پایین بردن", "⬇️", "", lambda: self.move_task(1)),
                         ("ثبت خط مبنا (تصویر برنامهٔ کنونی برای مقایسه)", "📌", "", self.set_baseline),
                         ("چاپ برنامهٔ زمان‌بندی", "🖨️", "", self.print_schedule),
                         ("خروجی Excel برنامهٔ زمان‌بندی", "📊", "", self.export_schedule)))
        progress = QHBoxLayout()
        self.percent_field = QDoubleSpinBox()
        self.percent_field.setRange(0, 100)
        self.percent_field.setSuffix("٪")
        self.actual_start_field = JalaliDateEdit(allow_empty=True)
        self.actual_finish_field = JalaliDateEdit(allow_empty=True)
        progress.addWidget(FieldGrid([
            FieldSpec("task_percent", "پیشرفت", self.percent_field, span=1),
            FieldSpec("task_astart", "شروع واقعی", self.actual_start_field, span=1),
            FieldSpec("task_afinish", "پایان واقعی", self.actual_finish_field, span=1)]), 1)
        record = _btn("ثبت پیشرفت فعالیت انتخاب‌شده", "✅", "primary")
        record.clicked.connect(self.record_progress)
        progress.addWidget(record)
        v.addLayout(progress)
        links = QHBoxLayout()
        self.pred_combo = combo([], "—")
        self.link_type_combo = QComboBox()
        for code, label in prj.LINK_TYPES.items():
            self.link_type_combo.addItem(label, code)
        self.lag_field = QSpinBox()
        self.lag_field.setRange(-365, 365)
        links.addWidget(FieldGrid([
            FieldSpec("link_pred", "پیش‌نیاز فعالیت انتخاب‌شده", self.pred_combo, span=1),
            FieldSpec("link_type", "نوع پیوند", self.link_type_combo, span=1),
            FieldSpec("link_lag", "فاصله (روز کاری)", self.lag_field, span=1)]), 1)
        for label, glyph, kind, slot in (("افزودن پیش‌نیاز", "🔗", "primary", self.add_link),
                                         ("برداشتن پیوند انتخاب‌شده", "✂️", "danger", self.remove_link)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            links.addWidget(button)
        v.addLayout(links)
        self.link_table = table(["پیش‌نیاز", "جانشین", "نوع پیوند", "فاصله"])
        self.link_table.setMaximumHeight(140)
        v.addWidget(self.link_table)
        return w

    def load_schedule(self) -> None:
        self.tree.clear()
        self.link_table.setRowCount(0)
        self.schedule = None
        self.links = []
        cid = company_id()
        if cid is None or self.project_id is None:
            self.summary_label.setText("ابتدا یک پروژه را در زبانهٔ «پروژه‌ها» انتخاب کنید.")
            self.gantt.set_schedule(None)
            self.load_costs()
            self.billing_tab.set_project(None)
            self.changes_tab.set_project(None)
            return
        try:
            self.schedule = sch.compute(cid, self.project_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return
        self.links = prj.list_links(cid, self.project_id)
        s = self.schedule
        project = next((p for p in self.projects if p.project_id == self.project_id), None)
        text = (f"پروژهٔ «{project.name if project else ''}» | شروع {numerals.format_jalali_date(s.start)} | پایان برنامه "
                f"{numerals.format_jalali_date(s.finish)} | پیشرفت واقعی {_pct(s.percent)} در برابر برنامه {_pct(s.planned_percent)}"
                f" | فعالیت بحرانی {P(s.critical_count)} | عقب‌افتاده {P(s.late_count)}")
        if s.baseline_finish:
            text += f" | پایان خط مبنا {numerals.format_jalali_date(s.baseline_finish)}"
        if project and project.target_end_date and s.finish > project.target_end_date:
            text += f" | پایان برنامه از پایان هدف ({numerals.format_jalali_date(project.target_end_date)}) دیرتر است"
        self.summary_label.setText(text)
        items: dict[int, QTreeWidgetItem] = {}
        danger = QColor(theme.DANGER)
        for t in s.tasks:
            values = [t.wbs, t.name, "نقطهٔ عطف" if t.is_milestone else P(t.duration), numerals.format_jalali_date(t.start),
                      numerals.format_jalali_date(t.finish), _ltr(P(t.predecessors)) if t.predecessors else "—", P(t.total_float), _pct(t.percent),
                      t.responsible or "—", t.state_label]
            item = QTreeWidgetItem([P(x) if i == 0 else x for i, x in enumerate(values)])
            item.setData(0, Qt.UserRole, t.task_id)
            if t.critical and not t.is_summary:
                for col in range(len(values)):
                    item.setForeground(col, danger)
            if t.is_summary:
                font = item.font(1)
                font.setBold(True)
                item.setFont(1, font)
            parent = items.get(t.parent_task_id)
            (parent.addChild(item) if parent is not None else self.tree.addTopLevelItem(item))
            items[t.task_id] = item
        self.tree.expandAll()
        for col in range(len(_TASK_HEADERS)):
            self.tree.resizeColumnToContents(col)
        by_id = s.by_id()
        for box, rows in ((self.parent_combo, [t for t in s.tasks if not t.is_milestone]), (self.pred_combo, [t for t in s.tasks if not t.is_summary])):
            current = box.currentData()
            box.clear()
            box.addItem("— بدون فاز —" if box is self.parent_combo else "—", None)
            for t in rows:
                box.addItem(P(f"{t.wbs} {t.name}"), t.task_id)
            set_combo(box, current)
        fill(self.link_table, [[f"{by_id[ln.predecessor_task_id].wbs} {by_id[ln.predecessor_task_id].name}",
                                f"{by_id[ln.successor_task_id].wbs} {by_id[ln.successor_task_id].name}", ln.type_label, ln.lag_days]
                               for ln in self.links], [ln.link_id for ln in self.links])
        self.gantt.set_schedule(s)
        self.load_costs()
        self.billing_tab.set_project(project)
        self.changes_tab.set_project(project)

    def _selected_task(self):
        items = self.tree.selectedItems()
        if not items or self.schedule is None:
            return None
        return self.schedule.by_id().get(items[0].data(0, Qt.UserRole))

    def _load_task(self) -> None:
        t = self._selected_task()
        if t is None:
            return
        self._task_id = t.task_id
        self.task_name_field.setText(t.name)
        set_combo(self.parent_combo, t.parent_task_id)
        self.duration_field.setValue(t.duration)
        self.sne_field.setDate(t.start_no_earlier)
        set_combo(self.responsible_combo, t.responsible_employee_id)
        self.hours_field.setValue(float(t.planned_hours))
        self.cost_field.setText(P(f"{t.planned_cost.normalize():f}") if t.planned_cost else "")
        self.task_notes_field.setText(t.notes)
        self.percent_field.setValue(float(t.percent))
        self.actual_start_field.setDate(t.actual_start)
        self.actual_finish_field.setDate(t.actual_finish)

    def new_task(self, keep_phase: bool = False) -> None:
        self._task_id = None
        if not keep_phase:
            set_combo(self.parent_combo, None)
        self.tree.clearSelection()
        for field in (self.task_name_field, self.cost_field, self.task_notes_field):
            field.clear()
        self.duration_field.setValue(1)
        self.sne_field.setDate(None)
        self.hours_field.setValue(0)
        set_combo(self.responsible_combo, None)

    def save_task(self) -> int | None:
        if self.project_id is None:
            self._status("ابتدا پروژه را انتخاب یا ذخیره کنید.", False)
            return None
        try:
            fields = prj.TaskFields(self.task_name_field.text(), self.duration_field.value(), self.parent_combo.currentData(),
                                    self.sne_field.date(), self.responsible_combo.currentData(),
                                    decimal.Decimal(str(self.hours_field.value())), dec(self.cost_field.text()), self.task_notes_field.text())
            task_id = prj.save_task(company_id(), self.project_id, fields, self._task_id)
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "هزینهٔ برنامه‌ای نامعتبر است.", False)
            return None
        self.new_task(keep_phase=True)  # فعالیت بعدی معمولاً در همان فاز است
        self.refresh()
        self._status("فعالیت ذخیره شد.", True)
        return task_id

    def delete_task(self) -> bool:
        t = self._selected_task()
        if t is None:
            self._status("یک فعالیت را انتخاب کنید.", False)
            return False
        try:
            prj.delete_task(company_id(), t.task_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.new_task()
        self.refresh()
        self._status("فعالیت حذف شد.", True)
        return True

    def move_task(self, step: int) -> bool:
        t = self._selected_task()
        if t is None:
            self._status("یک فعالیت را انتخاب کنید.", False)
            return False
        moved = prj.move_task(company_id(), t.task_id, step)
        self.refresh()
        return moved

    def record_progress(self) -> bool:
        t = self._selected_task()
        if t is None:
            self._status("یک فعالیت را انتخاب کنید.", False)
            return False
        try:
            prj.update_progress(company_id(), t.task_id, decimal.Decimal(str(self.percent_field.value())),
                                self.actual_start_field.date(), self.actual_finish_field.date())
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.refresh()
        self._status("پیشرفت ثبت شد.", True)
        return True

    def add_link(self) -> int | None:
        t = self._selected_task()
        pred = self.pred_combo.currentData()
        if t is None or pred is None:
            self._status("فعالیت جانشین را از فهرست و پیش‌نیاز را از فهرست کشویی انتخاب کنید.", False)
            return None
        try:
            link_id = prj.add_link(company_id(), pred, t.task_id, self.link_type_combo.currentData(), self.lag_field.value())
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self.refresh()
        self._status("پیوند ثبت شد.", True)
        return link_id

    def remove_link(self) -> bool:
        link_id = selected_data(self.link_table)
        if link_id is None:
            self._status("یک پیوند را از جدول پیوندها انتخاب کنید.", False)
            return False
        prj.remove_link(company_id(), link_id)
        self.refresh()
        self._status("پیوند برداشته شد.", True)
        return True

    def set_baseline(self) -> bool:
        if self.project_id is None:
            self._status("یک پروژه را انتخاب کنید.", False)
            return False
        try:
            count = prj.set_baseline(company_id(), self.project_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.refresh()
        self._status(f"خط مبنا برای {P(count)} فعالیت ثبت شد.", True)
        return True

    def _schedule_table(self):
        s = self.schedule
        headers = _TASK_HEADERS + ["شروع خط مبنا", "پایان خط مبنا", "هزینهٔ برنامه‌ای"]
        rows = [[t.wbs, ("    " * t.level) + t.name, "نقطهٔ عطف" if t.is_milestone else t.duration, t.start, t.finish,
                 t.predecessors or "—", t.total_float, _pct(t.percent), t.responsible or "—",
                 t.state_label + (" (بحرانی)" if t.critical and not t.is_summary else ""),
                 t.baseline_start or "—", t.baseline_finish or "—", t.planned_cost] for t in s.tasks]
        project = next((p for p in self.projects if p.project_id == self.project_id), None)
        head = [("پروژه", project.label if project else ""), ("پایان برنامه", numerals.format_jalali_date(s.finish)),
                ("پیشرفت واقعی", _pct(s.percent)), ("پیشرفت برنامه‌ای", _pct(s.planned_percent))]
        return "برنامهٔ زمان‌بندی پروژه", headers, rows, head

    def print_schedule(self) -> bool:
        if not self.schedule or not self.schedule.tasks:
            self._status("پروژهٔ انتخاب‌شده فعالیتی ندارد.", False)
            return False
        title, headers, rows, head = self._schedule_table()
        report_export.print_report(self, title, headers, rows, filters=head)
        return True

    def export_schedule(self) -> bool:
        if not self.schedule or not self.schedule.tasks:
            self._status("پروژهٔ انتخاب‌شده فعالیتی ندارد.", False)
            return False
        title, headers, rows, head = self._schedule_table()
        report_export.export_report_excel(self, title, headers, rows, filters=head)
        return True

    # --- گانت ------------------------------------------------------------------------------------------------------------
    def _gantt_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("مقیاس:"))
        self.zoom_combo = QComboBox()
        for code, (label, _px) in ZOOMS.items():
            self.zoom_combo.addItem(label, code)
        self.zoom_combo.currentIndexChanged.connect(lambda: self.gantt.set_zoom(self.zoom_combo.currentData()))
        row.addWidget(self.zoom_combo)
        legend = QLabel("نوار قرمز: فعالیت بحرانی | نوار تیره: فاز | لوزی: نقطهٔ عطف | خط خاکستری زیر نوار: خط مبنا | خط نارنجی: امروز")
        legend.setObjectName("mutedLabel")
        row.addWidget(legend, 1)
        v.addLayout(row)
        self.gantt = GanttChart()
        scroll = QScrollArea()
        scroll.setWidget(self.gantt)
        scroll.setWidgetResizable(True)
        v.addWidget(scroll, 1)
        return w

    # --- هزینه و کارکرد ------------------------------------------------------------------------------------------------
    def _cost_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.cost_from_field, self.cost_to_field = JalaliDateEdit(allow_empty=True), JalaliDateEdit(allow_empty=True)
        row.addWidget(FieldGrid([FieldSpec("cost_from", "از تاریخ", self.cost_from_field, span=1),
                                 FieldSpec("cost_to", "تا تاریخ", self.cost_to_field, span=1)], columns=2), 1)
        for label, glyph, kind, slot in (("نمایش هزینه", "🔎", "primary", self.load_costs),
                                         ("چاپ هزینه و کارکرد", "🖨️", "", self.print_costs),
                                         ("خروجی Excel هزینه و کارکرد", "📊", "", self.export_costs)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            row.addWidget(button)
        v.addLayout(row)
        self.cost_label = QLabel("")
        self.cost_label.setWordWrap(True)
        v.addWidget(self.cost_label)
        note = QLabel("هزینهٔ دفاتر از اسناد حسابداری با تفصیلی همین پروژه (حساب‌های هزینه و بهای تمام‌شده) و درآمد از حساب‌های درآمد "
                      "می‌آید. هزینهٔ کارکرد = ساعت تاییدشده × نرخ ساعتی و فقط محاسباتی است؛ اگر حقوق را با تفصیلی پروژه در دفاتر ثبت "
                      "می‌کنید آن را دوباره نشمارید.")
        note.setWordWrap(True)
        note.setObjectName("mutedLabel")
        v.addWidget(note)
        self.cost_table = table(["کد حساب", "حساب", "نوع", "مبلغ"])
        v.addWidget(self.cost_table, 1)
        self.labor_table = table(["شماره", "فعالیت", "ساعت برنامه‌ای", "ساعت تاییدشده", "هزینهٔ برنامه‌ای", "هزینهٔ کارکرد"])
        v.addWidget(self.labor_table, 1)
        self.costs = None
        return w

    def load_costs(self) -> None:
        self.costs = None
        self.cost_table.setRowCount(0)
        self.labor_table.setRowCount(0)
        if company_id() is None or self.project_id is None:
            self.cost_label.setText("")
            return
        c = self.costs = prj_costs.project_cost(company_id(), self.project_id, self.cost_from_field.date(), self.cost_to_field.date())
        budget = c.baseline_cost if c.baseline_cost is not None else c.planned_cost
        text = (f"مبلغ قرارداد {money(c.contract_amount)} | بودجهٔ هزینه {money(budget)}"
                f"{' (خط مبنا)' if c.baseline_cost is not None else ' (برنامه)'} | هزینهٔ دفاتر {money(c.gl_cost)} | "
                f"کارکرد {P(f'{c.labor_hours.normalize():f}')} ساعت = {money(c.labor_cost)} | جمع هزینه {money(c.total_cost)} | "
                f"ماندهٔ بودجه {money(c.budget_left)} | درآمد {money(c.revenue)} | سود ناخالص {money(c.margin)}")
        if c.pending_hours:
            text += f" | {P(f'{c.pending_hours.normalize():f}')} ساعت منتظر تایید"
        if c.unpriced_hours:
            text += f" | {P(f'{c.unpriced_hours.normalize():f}')} ساعت بدون نرخ ساعتی"
        self.cost_label.setText(text)
        rows = [[a.full_code, a.name, "هزینه", a.amount] for a in c.cost_accounts]
        rows += [[a.full_code, a.name, "درآمد", a.amount] for a in c.revenue_accounts]
        fill(self.cost_table, rows)
        fill(self.labor_table, [[t.wbs or "—", t.name, P(f"{t.planned_hours.normalize():f}"), P(f"{t.hours.normalize():f}"),
                                 t.planned_cost, t.cost] for t in c.tasks])

    def _cost_report(self):
        c = self.costs
        headers = ["بخش", "شرح", "ساعت برنامه‌ای", "ساعت تاییدشده", "برنامه", "واقعی"]
        rows = [["دفاتر", f"{a.full_code} {a.name}", "", "", "", a.amount] for a in c.cost_accounts]
        rows += [["کارکرد", f"{t.wbs} {t.name}".strip(), t.planned_hours, t.hours, t.planned_cost, t.cost] for t in c.tasks]
        rows += [["درآمد", f"{a.full_code} {a.name}", "", "", "", a.amount] for a in c.revenue_accounts]
        project = next((p for p in self.projects if p.project_id == self.project_id), None)
        head = [("پروژه", project.label if project else ""), ("جمع هزینه", money(c.total_cost)), ("درآمد", money(c.revenue)),
                ("سود ناخالص", money(c.margin))]
        return "هزینه و کارکرد پروژه", headers, rows, head

    def print_costs(self) -> bool:
        if self.costs is None:
            self._status("یک پروژه را انتخاب کنید.", False)
            return False
        title, headers, rows, head = self._cost_report()
        report_export.print_report(self, title, headers, rows, filters=head)
        return True

    def export_costs(self) -> bool:
        if self.costs is None:
            self._status("یک پروژه را انتخاب کنید.", False)
            return False
        title, headers, rows, head = self._cost_report()
        report_export.export_report_excel(self, title, headers, rows, filters=head)
        return True
