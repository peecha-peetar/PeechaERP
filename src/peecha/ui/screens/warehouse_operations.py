"""جانمایی، برداشت و برنامهٔ شمارشِ دوره‌ای -- R247 (WMS سبک)."""

from __future__ import annotations

import decimal

from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha import session as app_session
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import warehouse_operations as ops
from peecha.ui import theme


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _fmt_dt(value) -> str:
    return numerals.format_jalali_datetime(value) if value else ""


class _TasksTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        hint = QLabel("وظیفهٔ جانمایی برایِ رسیدِ ثبت‌شده و وظیفهٔ برداشت برایِ حواله/سفارشِ منتظرِ انبار ساخته می‌شود. "
                      "تکمیلِ جانمایی با سندِ انتقالِ عادیِ سیستم کالا را به محلِ مقصد می‌برد؛ برداشت فقط مقدار و زمان را ثبت می‌کند.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        top = QHBoxLayout()
        top.addWidget(QLabel("نوع:"))
        self.type_combo = QComboBox()
        for code, label in ops.TASK_TYPES.items():
            self.type_combo.addItem(label, code)
        self.type_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        top.addWidget(self.type_combo)
        top.addWidget(QLabel("وضعیت:"))
        self.status_combo = QComboBox()
        self.status_combo.addItem("— همه —", None)
        for code, label in ops.TASK_STATUSES.items():
            self.status_combo.addItem(label, code)
        self.status_combo.currentIndexChanged.connect(lambda _i: self._load())
        top.addWidget(self.status_combo)
        top.addSpacing(20)
        top.addWidget(QLabel("ایجاد از سند:"))
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(280)
        top.addWidget(self.source_combo)
        generate = QPushButton("ایجادِ وظایف")
        generate.setObjectName("primaryButton")
        generate.clicked.connect(self.generate_selected)
        top.addWidget(generate)
        top.addStretch(1)
        layout.addLayout(top)
        self.table = _table(["شماره", "نوع", "انبار", "کالا", "مقدار", "انجام‌شده", "از محل", "به محل", "وضعیت", "اپراتور",
                             "ایجاد", "شروع", "تکمیل"])
        layout.addWidget(self.table, stretch=1)
        actions = QHBoxLayout()
        for text, slot in (("شروع", self.start_selected), ("تکمیل…", self.complete_selected), ("لغو", self.cancel_selected)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        self.status_label = QLabel("")
        actions.addWidget(self.status_label)
        layout.addLayout(actions)
        self._tasks = []

    def _company_id(self):
        return app_session.current_company.company_id if app_session.current_company else None

    def _user_id(self):
        return app_session.current_user.user_id if app_session.current_user else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._items = {i.item_id: f"{i.code} — {i.name or ''}" for i in catalog_service.list_items(company_id)}
        self._whs = {w.warehouse_id: w.name for w in locations_service.list_warehouses(company_id)}
        self._bins = {b.bin_location_id: b.code for wid in self._whs for b in locations_service.list_bin_locations(wid)}
        from peecha.db.base import new_session
        from peecha.db.models.security import User
        from sqlalchemy import select

        with new_session() as session:
            self._users = dict(session.execute(select(User.user_id, User.full_name)).all())
        task_type = self.type_combo.currentData()
        self.source_combo.clear()
        if task_type == "REPLENISH":
            needs = ops.replenishment_needs(company_id)
            if needs:
                self.source_combo.addItem(numerals.to_persian_digits(f"{len(needs)} محلِ زیرِ حداقل"), ("REPLENISH", 0))
            self._load()
            return
        sources = ops.putaway_sources(company_id) if task_type == "PUTAWAY" else ops.pick_sources(company_id)
        for s in sources:
            d = s.doc
            label = (f"{d.document_type_code} {d.document_no} — {numerals.format_jalali_date(d.document_date)}")
            self.source_combo.addItem(numerals.to_persian_digits(label), s.key)
        self._load()

    def _load(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._tasks = ops.list_tasks(company_id, self.type_combo.currentData(), self.status_combo.currentData())
        self.table.setRowCount(len(self._tasks))
        for row, t in enumerate(self._tasks):
            cells = [str(t.task_id), ops.TASK_TYPES[t.task_type_code], self._whs.get(t.warehouse_id, ""), self._items.get(t.item_id, ""),
                     numerals.format_money(t.quantity_base, 2, None),
                     numerals.format_money(t.done_quantity_base, 2, None) if t.done_quantity_base is not None else "",
                     self._bins.get(t.from_bin_location_id, ""), self._bins.get(t.to_bin_location_id, ""),
                     ops.TASK_STATUSES[t.status_code], self._users.get(t.completed_by_user_id or t.assigned_user_id, ""),
                     _fmt_dt(t.created_at), _fmt_dt(t.started_at), _fmt_dt(t.completed_at)]
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(numerals.to_persian_digits(text)))

    def _selected(self):
        row = self.table.currentRow()
        return self._tasks[row] if 0 <= row < len(self._tasks) else None

    def _run(self, fn, ok_text: str) -> bool:
        try:
            fn()
        except ValueError as exc:
            QMessageBox.warning(self, "وظایفِ انبار", str(exc))
            return False
        theme.set_status_label(self.status_label, ok_text, ok=True)
        self.refresh()
        return True

    def generate_selected(self) -> bool:
        source = self.source_combo.currentData()
        if source is None:
            return False
        if self.type_combo.currentData() == "REPLENISH":
            return self._run(lambda: ops.generate_replenishment_tasks(self._company_id(), self._user_id()), "وظایفِ تأمینِ مجدد ساخته شد.")
        return self._run(lambda: ops.generate_tasks(self._company_id(), self.type_combo.currentData(), tuple(source), self._user_id()),
                         "وظایف ساخته شد.")

    def start_selected(self) -> bool:
        task = self._selected()
        return bool(task) and self._run(lambda: ops.start_task(task.task_id, self._company_id(), self._user_id()), "وظیفه شروع شد.")

    def cancel_selected(self) -> bool:
        task = self._selected()
        return bool(task) and self._run(lambda: ops.cancel_task(task.task_id, self._company_id()), "وظیفه لغو شد.")

    def complete_selected(self, value=None) -> bool:
        """value: برایِ جانمایی شناسهٔ محلِ مقصد، برایِ برداشت مقدارِ برداشته (اگر None باشد از کاربر پرسیده می‌شود)."""
        task = self._selected()
        if task is None:
            return False
        company_id, user_id = self._company_id(), self._user_id()
        if task.task_type_code == "PUTAWAY":
            if value is None:
                bins = locations_service.list_bin_locations(task.warehouse_id, active_only=True)
                labels = [f"{b.code} — {b.name or ''}" for b in bins]
                choice, ok = QInputDialog.getItem(self, "جانمایی", "محلِ مقصد:", labels, 0, False)
                if not ok:
                    return False
                value = bins[labels.index(choice)].bin_location_id
            return self._run(lambda: ops.complete_putaway(task.task_id, company_id, user_id, value), "جانمایی انجام شد.")
        if task.task_type_code == "REPLENISH":
            if value is None:
                qty, ok = QInputDialog.getDouble(self, "تأمینِ مجدد", "مقدارِ جابه‌جاشده:", float(task.quantity_base), 0.001,
                                                 float(task.quantity_base), 3)
                if not ok:
                    return False
                value = decimal.Decimal(str(qty))
            return self._run(lambda: ops.complete_replenishment(task.task_id, company_id, user_id, value), "تأمینِ مجدد انجام شد.")
        if value is None:
            qty, ok = QInputDialog.getDouble(self, "برداشت", "مقدارِ برداشته (واحدِ اصلی):", float(task.quantity_base), 0, 1e12, 3)
            if not ok:
                return False
            value = decimal.Decimal(str(qty))
        return self._run(lambda: ops.complete_pick(task.task_id, company_id, user_id, value), "برداشت ثبت شد.")


class _PlansTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        hint = QLabel("برایِ هر انبار مشخص کنید کدام کالاها (یک کالا، یک گروه، یک کلاسِ ABC یا همه) هر چند روز یک‌بار شمرده شوند. "
                      "گزارشِ «شمارش‌هایِ سررسیدشده» فهرستِ کارِ امروز را می‌دهد.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QHBoxLayout()
        self.code_field = QLineEdit()
        self.code_field.setPlaceholderText("کد")
        self.code_field.setMaximumWidth(90)
        self.name_field = QLineEdit()
        self.name_field.setPlaceholderText("نام")
        self.warehouse_combo = QComboBox()
        self.scope_combo = QComboBox()
        self.scope_combo.setMinimumWidth(200)
        self.frequency_spin = QSpinBox()
        self.frequency_spin.setRange(1, 3650)
        self.frequency_spin.setValue(30)
        self.frequency_spin.setSuffix(" روز")
        self.active_check = QCheckBox("فعال")
        self.active_check.setChecked(True)
        for label, widget in (("", self.code_field), ("", self.name_field), ("انبار:", self.warehouse_combo),
                              ("دامنه:", self.scope_combo), ("تواتر:", self.frequency_spin)):
            if label:
                form.addWidget(QLabel(label))
            form.addWidget(widget)
        form.addWidget(self.active_check)
        save = QPushButton("ذخیره")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save)
        form.addWidget(save)
        new = QPushButton("جدید")
        new.clicked.connect(self._clear)
        form.addWidget(new)
        delete = QPushButton("حذف")
        delete.clicked.connect(self.delete_selected)
        form.addWidget(delete)
        layout.addLayout(form)
        self.table = _table(["کد", "نام", "انبار", "دامنه", "تواتر (روز)", "فعال", "اقلامِ سررسید"])
        self.table.itemSelectionChanged.connect(self._load_selected)
        layout.addWidget(self.table, stretch=1)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        self._plans, self._editing = [], None

    def _company_id(self):
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.warehouse_combo.clear()
        for w in locations_service.list_warehouses(company_id, active_only=True):
            self.warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)
        self.scope_combo.clear()
        self.scope_combo.addItem("همهٔ کالاهایِ انبار", ("ALL", None))
        for cls in "ABC":
            self.scope_combo.addItem(f"کلاسِ {cls} (ABC)", ("ABC", cls))
        for c in catalog_service.list_categories(company_id):
            self.scope_combo.addItem(f"گروه: {c.code} — {c.name}", ("CATEGORY", c.category_id))
        for i in catalog_service.list_items(company_id, transactable_only=True):
            self.scope_combo.addItem(numerals.to_persian_digits(f"کالا: {i.code} — {i.name or ''}"), ("ITEM", i.item_id))
        self._plans = ops.list_plans(company_id)
        due: dict[int, int] = {}
        for d in ops.due_counts(company_id):
            due[d.plan.plan_id] = due.get(d.plan.plan_id, 0) + 1
        self.table.setRowCount(len(self._plans))
        for row, p in enumerate(self._plans):
            scope_index = self._scope_index(p)
            cells = [p.code, p.name, self.warehouse_combo.itemText(max(0, self.warehouse_combo.findData(p.warehouse_id))),
                     self.scope_combo.itemText(scope_index), str(p.frequency_days), "بله" if p.is_active else "خیر",
                     str(due.get(p.plan_id, 0))]
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(numerals.to_persian_digits(text)))

    def _scope_index(self, p) -> int:
        key = ("ITEM", p.item_id) if p.item_id else ("CATEGORY", p.category_id) if p.category_id else \
            ("ABC", p.abc_class) if p.abc_class else ("ALL", None)
        for i in range(self.scope_combo.count()):
            if tuple(self.scope_combo.itemData(i)) == key:
                return i
        return 0

    def _clear(self) -> None:
        self._editing = None
        self.code_field.clear()
        self.name_field.clear()
        self.frequency_spin.setValue(30)
        self.active_check.setChecked(True)

    def _load_selected(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self._plans)):
            return
        p = self._plans[row]
        self._editing = p.plan_id
        self.code_field.setText(p.code)
        self.name_field.setText(p.name)
        self.warehouse_combo.setCurrentIndex(max(0, self.warehouse_combo.findData(p.warehouse_id)))
        self.scope_combo.setCurrentIndex(self._scope_index(p))
        self.frequency_spin.setValue(p.frequency_days)
        self.active_check.setChecked(p.is_active)

    def save(self) -> bool:
        kind, value = tuple(self.scope_combo.currentData() or ("ALL", None))
        fields = ops.PlanFields(
            code=self.code_field.text(), name=self.name_field.text(), warehouse_id=self.warehouse_combo.currentData(),
            frequency_days=self.frequency_spin.value(), item_id=value if kind == "ITEM" else None,
            category_id=value if kind == "CATEGORY" else None, abc_class=value if kind == "ABC" else None,
            is_active=self.active_check.isChecked())
        try:
            ops.save_plan(self._company_id(), fields, self._editing)
        except ValueError as exc:
            QMessageBox.warning(self, "برنامهٔ شمارش", str(exc))
            return False
        theme.set_status_label(self.status_label, "برنامه ذخیره شد.", ok=True)
        self._clear()
        self.refresh()
        return True

    def delete_selected(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._plans):
            ops.delete_plan(self._company_id(), self._plans[row].plan_id)
            self._clear()
            self.refresh()


class _ReplenishTab(QWidget):
    """R249: حداقل/حداکثرِ کالا در محلِ برداشت و نیازهایِ تأمینِ مجدد."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        hint = QLabel("برایِ هر محلِ برداشت، حداقل و حداکثرِ کالا را تعریف کنید. وقتی موجودیِ محل به حداقل برسد، "
                      "وظیفهٔ تأمینِ مجدد از محل‌هایِ ذخیره/حجیمِ همان انبار ساخته و مقدارش رزرو می‌شود.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QHBoxLayout()
        self.warehouse_combo = QComboBox()
        self.warehouse_combo.currentIndexChanged.connect(lambda _i: self._fill_locations())
        self.location_combo = QComboBox()
        self.location_combo.setMinimumWidth(220)
        self.item_combo = QComboBox()
        self.item_combo.setMinimumWidth(220)
        self.min_spin, self.max_spin = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.min_spin, self.max_spin):
            spin.setRange(0, 1e9)
            spin.setDecimals(3)
        for label, widget in (("انبار:", self.warehouse_combo), ("محل:", self.location_combo), ("کالا:", self.item_combo),
                              ("حداقل:", self.min_spin), ("حداکثر:", self.max_spin)):
            form.addWidget(QLabel(label))
            form.addWidget(widget)
        save = QPushButton("ذخیرهٔ قاعده")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save)
        form.addWidget(save)
        form.addStretch(1)
        layout.addLayout(form)
        self.table = _table(["محل", "کالا", "حداقل", "حداکثر", "موجودیِ محل", "نیاز", "منابع", "فعال"])
        layout.addWidget(self.table, stretch=1)
        actions = QHBoxLayout()
        delete = QPushButton("حذف/غیرفعال‌سازیِ قاعده")
        delete.clicked.connect(self.delete_selected)
        generate = QPushButton("ایجادِ وظایفِ تأمینِ مجدد")
        generate.clicked.connect(self.generate)
        actions.addWidget(delete)
        actions.addWidget(generate)
        actions.addStretch(1)
        self.status_label = QLabel("")
        actions.addWidget(self.status_label)
        layout.addLayout(actions)
        self._rules = []

    def _company_id(self):
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.warehouse_combo.blockSignals(True)
        self.warehouse_combo.clear()
        for w in locations_service.list_warehouses(company_id):
            self.warehouse_combo.addItem(w.name, w.warehouse_id)
        self.warehouse_combo.blockSignals(False)
        self.item_combo.clear()
        items = catalog_service.list_items(company_id, transactable_only=True)
        self._items = {i.item_id: f"{i.code} — {i.name or ''}" for i in items}
        for i in items:
            self.item_combo.addItem(self._items[i.item_id], i.item_id)
        self._fill_locations()
        self._load()

    def _fill_locations(self) -> None:
        from peecha.services import warehouse_locations as wl

        self.location_combo.clear()
        wid = self.warehouse_combo.currentData()
        if wid is None:
            return
        nodes = wl.tree(self._company_id(), wid, active_only=True)
        parents = {n.parent_id for n in nodes}
        for n in nodes:
            if n.location_id not in parents and n.allow_replenishment:
                self.location_combo.addItem(n.full_code, n.location_id)

    def _load(self) -> None:
        from peecha.services import warehouse_locations as wl

        company_id = self._company_id()
        self._rules = ops.list_rules(company_id)
        needs = {n.rule.rule_id: n for n in ops.replenishment_needs(company_id)}
        codes = {}
        for wid in {self.warehouse_combo.itemData(i) for i in range(self.warehouse_combo.count())}:
            codes.update({n.location_id: n.full_code for n in wl.tree(company_id, wid)})
        self.table.setRowCount(len(self._rules))
        for row, r in enumerate(self._rules):
            need = needs.get(r.rule_id)
            cells = [codes.get(r.bin_location_id, ""), self._items.get(r.item_id, ""), numerals.format_money(r.min_quantity, 3, None),
                     numerals.format_money(r.max_quantity, 3, None),
                     numerals.format_money(need.on_hand, 3, None) if need else "",
                     numerals.format_money(need.need, 3, None) if need else "",
                     "، ".join(s.location_code for s in need.sources[:3]) if need else "", "بله" if r.is_active else "خیر"]
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(numerals.to_persian_digits(text)))

    def save(self) -> bool:
        try:
            ops.save_rule(self._company_id(), ops.RuleFields(
                self.location_combo.currentData(), self.item_combo.currentData(),
                decimal.Decimal(str(self.min_spin.value())), decimal.Decimal(str(self.max_spin.value()))))
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "تأمینِ مجدد", str(exc))
            return False
        theme.set_status_label(self.status_label, "قاعده ذخیره شد.", ok=True)
        self._load()
        return True

    def delete_selected(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._rules):
            ops.delete_rule(self._company_id(), self._rules[row].rule_id)
            self._load()

    def generate(self) -> list[int]:
        ids = ops.generate_replenishment_tasks(self._company_id(), app_session.current_user.user_id)
        theme.set_status_label(self.status_label, numerals.to_persian_digits(f"{len(ids)} وظیفهٔ تأمینِ مجدد ساخته شد."), ok=True)
        self._load()
        return ids


class _WavesTab(QWidget):
    """R250: موجِ برداشت -- گروه‌بندیِ وظایفِ برداشت با ترتیبِ مسیرِ بهینه."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        hint = QLabel("وظایفِ برداشتِ بازِ یک انبار در یک موج جمع و به ترتیبِ کوتاه‌ترین مسیر (از منطقهٔ برداشت تا ارسال) مرتب می‌شوند.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        top = QHBoxLayout()
        top.addWidget(QLabel("انبار:"))
        self.warehouse_combo = QComboBox()
        top.addWidget(self.warehouse_combo)
        create = QPushButton("ساختِ موج از وظایفِ باز")
        create.setObjectName("primaryButton")
        create.clicked.connect(self.create)
        top.addWidget(create)
        top.addStretch(1)
        layout.addLayout(top)
        self.waves_table = _table(["موج", "انبار", "وضعیت", "مسیر (متر)", "وظایف", "انجام‌شده", "ایجاد"])
        self.waves_table.itemSelectionChanged.connect(self._load_tasks)
        layout.addWidget(self.waves_table, stretch=1)
        self.tasks_table = _table(["ترتیب", "وظیفه", "کالا", "مقدار", "از محل", "وضعیت"])
        layout.addWidget(self.tasks_table, stretch=1)
        actions = QHBoxLayout()
        for text, slot in (("لغوِ موج", self.release_selected), ("نمایشِ مسیر رویِ نقشه", self.show_on_map)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            actions.addWidget(b)
        actions.addStretch(1)
        self.status_label = QLabel("")
        actions.addWidget(self.status_label)
        layout.addLayout(actions)
        self._waves, self._tasks = [], []

    def _company_id(self):
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        current = self.warehouse_combo.currentData()
        self.warehouse_combo.clear()
        self._whs = {}
        for w in locations_service.list_warehouses(company_id):
            self.warehouse_combo.addItem(w.name, w.warehouse_id)
            self._whs[w.warehouse_id] = w.name
        if current is not None:
            self.warehouse_combo.setCurrentIndex(max(0, self.warehouse_combo.findData(current)))
        self._items = {i.item_id: f"{i.code} — {i.name or ''}" for i in catalog_service.list_items(company_id)}
        self._waves = ops.list_waves(company_id)
        self.waves_table.setRowCount(len(self._waves))
        for row, w in enumerate(self._waves):
            tasks = ops.wave_tasks(company_id, w.wave_id)
            done = sum(1 for t in tasks if t.status_code == "DONE")
            cells = [w.wave_code, self._whs.get(w.warehouse_id, ""), {"OPEN": "باز", "DONE": "انجام‌شده", "CANCELLED": "لغوشده"}[w.status_code],
                     numerals.format_money((w.path_distance or 0) / 20, 1, None), str(len(tasks)), str(done), _fmt_dt(w.created_at)]
            for col, text in enumerate(cells):
                self.waves_table.setItem(row, col, QTableWidgetItem(numerals.to_persian_digits(text)))
        self._load_tasks()

    def _selected(self):
        row = self.waves_table.currentRow()
        return self._waves[row] if 0 <= row < len(self._waves) else None

    def _load_tasks(self) -> None:
        wave = self._selected()
        self._tasks = ops.wave_tasks(self._company_id(), wave.wave_id) if wave else []
        codes = {}
        if wave:
            from peecha.services import warehouse_locations as wl

            codes = {n.location_id: n.full_code for n in wl.tree(self._company_id(), wave.warehouse_id)}
        self.tasks_table.setRowCount(len(self._tasks))
        for row, t in enumerate(self._tasks):
            cells = [str(t.wave_sequence or ""), str(t.task_id), self._items.get(t.item_id, ""), numerals.format_money(t.quantity_base, 2, None),
                     codes.get(t.from_bin_location_id, ""), ops.TASK_STATUSES[t.status_code]]
            for col, text in enumerate(cells):
                self.tasks_table.setItem(row, col, QTableWidgetItem(numerals.to_persian_digits(text)))

    def create(self) -> int | None:
        try:
            wave_id = ops.create_wave(self._company_id(), self.warehouse_combo.currentData(), app_session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "موجِ برداشت", str(exc))
            return None
        theme.set_status_label(self.status_label, "موج ساخته شد.", ok=True)
        self.refresh()
        self.waves_table.selectRow(0)
        return wave_id

    def release_selected(self) -> None:
        wave = self._selected()
        if wave is None:
            return
        try:
            ops.release_wave(self._company_id(), wave.wave_id)
        except ValueError as exc:
            QMessageBox.warning(self, "موجِ برداشت", str(exc))
            return
        self.refresh()

    def show_on_map(self) -> bool:
        from PySide6.QtWidgets import QApplication

        wave = self._selected()
        if wave is None:
            return False
        bins = [t.from_bin_location_id for t in self._tasks if t.from_bin_location_id and t.status_code in ("OPEN", "IN_PROGRESS")]
        main = next((w for w in QApplication.topLevelWidgets() if hasattr(w, "open_screen") and hasattr(w, "_screens")), None)
        if main is None or not bins:
            return False
        main.open_screen("INV_WAREHOUSE_MAP", then=lambda screen: (screen.load_warehouse(wave.warehouse_id), screen.show_picking_path(bins)))
        return True


class _LocationCountTab(QWidget):
    """R250: شمارشِ دوره‌ایِ محل‌محور (کور)؛ اختلاف با سندِ اصلاحِ انبار رویِ همان محل."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        hint = QLabel("یک منطقه/قفسه/محل را انتخاب کنید تا موجودیِ دفتریِ همهٔ محل‌هایِ زیرش ثبت شود؛ انباردار (اینجا یا در موبایل) "
                      "شمارش می‌کند و با «نهایی‌سازی» اختلاف رویِ همان محل اصلاح می‌شود. کالاهایِ بچ/سریال‌دار با انبارگردانیِ عادی.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        top = QHBoxLayout()
        self.warehouse_combo = QComboBox()
        self.warehouse_combo.currentIndexChanged.connect(lambda _i: self._fill_locations())
        self.location_combo = QComboBox()
        self.location_combo.setMinimumWidth(240)
        self.blind_check = QCheckBox("شمارشِ کور")
        self.blind_check.setChecked(True)
        for label, widget in (("انبار:", self.warehouse_combo), ("محل:", self.location_combo)):
            top.addWidget(QLabel(label))
            top.addWidget(widget)
        top.addWidget(self.blind_check)
        create = QPushButton("شروعِ شمارش")
        create.setObjectName("primaryButton")
        create.clicked.connect(self.create)
        top.addWidget(create)
        top.addSpacing(16)
        top.addWidget(QLabel("شمارش:"))
        self.session_combo = QComboBox()
        self.session_combo.setMinimumWidth(160)
        self.session_combo.currentIndexChanged.connect(lambda _i: self._load_lines())
        top.addWidget(self.session_combo)
        top.addStretch(1)
        layout.addLayout(top)
        self.table = _table(["محل", "کالا", "دفتری", "شمارش", "اختلاف", "زمانِ شمارش"])
        layout.addWidget(self.table, stretch=1)
        actions = QHBoxLayout()
        for text, slot in (("ثبتِ شمارش…", self.record_selected), ("نهایی‌سازی و اصلاحِ اختلاف", self.finalize), ("لغوِ شمارش", self.cancel)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            actions.addWidget(b)
        actions.addStretch(1)
        self.status_label = QLabel("")
        actions.addWidget(self.status_label)
        layout.addLayout(actions)
        self._lines = []

    def _company_id(self):
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        from peecha.services import location_counts as lc

        company_id = self._company_id()
        if company_id is None:
            return
        self.warehouse_combo.blockSignals(True)
        self.warehouse_combo.clear()
        for w in locations_service.list_warehouses(company_id):
            self.warehouse_combo.addItem(w.name, w.warehouse_id)
        self.warehouse_combo.blockSignals(False)
        self._fill_locations()
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        for s in lc.list_location_counts(company_id, open_only=True):
            self.session_combo.addItem(s.session_code, s.session_id)
        self.session_combo.blockSignals(False)
        self._load_lines()

    def _fill_locations(self) -> None:
        from peecha.services import warehouse_locations as wl

        self.location_combo.clear()
        wid = self.warehouse_combo.currentData()
        if wid is None:
            return
        for n in wl.tree(self._company_id(), wid, active_only=True):
            if n.level is not None:
                self.location_combo.addItem(f"{n.full_code} ({wl.LEVEL_LABELS.get(n.level, '')})", n.location_id)

    def _load_lines(self) -> None:
        from peecha.services import location_counts as lc

        sid = self.session_combo.currentData()
        self._lines = lc.count_lines(self._company_id(), sid) if sid else []
        self.table.setRowCount(len(self._lines))
        fmt = lambda v: numerals.format_money(v, 3, None) if v is not None else ""  # noqa: E731
        for row, ln in enumerate(self._lines):
            cells = [ln.location_code, f"{ln.item_code} — {ln.item_name}" + (f" (بچ {ln.batch_no})" if ln.batch_no else ""),
                     "—" if ln.blind and ln.counted is None else fmt(ln.expected),
                     fmt(ln.counted), fmt(ln.variance), _fmt_dt(ln.counted_at)]
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(numerals.to_persian_digits(text)))

    def create(self) -> int | None:
        from peecha.services import location_counts as lc

        try:
            sid = lc.create_location_count(self._company_id(), self.warehouse_combo.currentData(), [self.location_combo.currentData()],
                                           app_session.current_user.user_id, blind=self.blind_check.isChecked())
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "شمارشِ محل", str(exc))
            return None
        self.refresh()
        self.session_combo.setCurrentIndex(max(0, self.session_combo.findData(sid)))
        theme.set_status_label(self.status_label, "شمارش شروع شد.", ok=True)
        return sid

    def record_selected(self, value=None) -> bool:
        from peecha.services import location_counts as lc

        row = self.table.currentRow()
        if not (0 <= row < len(self._lines)):
            return False
        ln = self._lines[row]
        if ln.serial:  # R252: کالایِ سریال‌دار با فهرستِ سریال‌ها
            if value is None:
                text, ok = QInputDialog.getMultiLineText(self, "شمارشِ سریال", f"سریال‌هایِ موجود در {ln.location_code} (هر خط یکی):")
                if not ok:
                    return False
                value = [x.strip() for x in text.splitlines() if x.strip()]
            try:
                lc.record_serial_count(self._company_id(), self.session_combo.currentData(), ln.location_id, ln.item_id, list(value),
                                       app_session.current_user.user_id)
            except ValueError as exc:
                QMessageBox.warning(self, "شمارشِ محل", str(exc))
                return False
            self._load_lines()
            return True
        if value is None:
            qty, ok = QInputDialog.getDouble(self, "شمارشِ محل", f"مقدارِ شمرده‌شده در {ln.location_code}:", 0, 0, 1e12, 3)
            if not ok:
                return False
            value = decimal.Decimal(str(qty))
        try:
            lc.record_location_count(self._company_id(), self.session_combo.currentData(), ln.location_id, ln.item_id, value,
                                     app_session.current_user.user_id, ln.batch_no)
        except ValueError as exc:
            QMessageBox.warning(self, "شمارشِ محل", str(exc))
            return False
        self._load_lines()
        return True

    def finalize(self) -> list[int]:
        from peecha.services import location_counts as lc

        sid = self.session_combo.currentData()
        if sid is None:
            return []
        try:
            docs = lc.finalize_location_count(self._company_id(), sid, app_session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "شمارشِ محل", str(exc))
            return []
        theme.set_status_label(self.status_label, numerals.to_persian_digits(f"شمارش بسته شد؛ {len(docs)} سندِ اصلاح."), ok=True)
        self.refresh()
        return docs

    def cancel(self) -> None:
        from peecha.services import location_counts as lc

        sid = self.session_combo.currentData()
        if sid is not None:
            lc.cancel_location_count(self._company_id(), sid)
            self.refresh()


class _KpiTab(QWidget):
    """R251: داشبوردِ عملیاتِ انبار -- شاخص‌ها، وظایف به تفکیکِ نوع و بهره‌وریِ اپراتور."""

    def __init__(self) -> None:
        super().__init__()
        from PySide6.QtWidgets import QGridLayout

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("انبار:"))
        self.warehouse_combo = QComboBox()
        self.warehouse_combo.currentIndexChanged.connect(lambda _i: self._load())
        top.addWidget(self.warehouse_combo)
        top.addWidget(QLabel("روزهایِ اخیر:"))
        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 365)
        self.days_spin.setValue(30)
        self.days_spin.valueChanged.connect(lambda _v: self._load())
        top.addWidget(self.days_spin)
        top.addStretch(1)
        layout.addLayout(top)
        self.cards = QGridLayout()
        layout.addLayout(self.cards)
        self.card_labels: dict[str, QLabel] = {}
        self.type_table = _table(["نوع", "انجام‌شده", "باز", "میانگینِ زمان (دقیقه)"])
        self.operator_table = _table(["اپراتور", "وظایف", "ساعت", "وظیفه در ساعت", "برداشت", "دقتِ برداشت"])
        layout.addWidget(self.type_table, stretch=1)
        layout.addWidget(self.operator_table, stretch=1)
        self.result = None

    def _company_id(self):
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.warehouse_combo.blockSignals(True)
        self.warehouse_combo.clear()
        self.warehouse_combo.addItem("— همه —", None)
        for w in locations_service.list_warehouses(company_id):
            self.warehouse_combo.addItem(w.name, w.warehouse_id)
        self.warehouse_combo.blockSignals(False)
        self._load()

    def _load(self) -> None:
        import datetime

        from peecha.services import wms_kpis

        company_id = self._company_id()
        if company_id is None:
            return
        today = datetime.date.today()
        self.result = wms_kpis.dashboard(company_id, today - datetime.timedelta(days=self.days_spin.value()), today,
                                         self.warehouse_combo.currentData())
        for i, (code, title, value, unit) in enumerate(self.result.kpis):
            if code not in self.card_labels:
                card = QLabel()
                card.setObjectName("card")
                card.setWordWrap(True)
                card.setMinimumHeight(64)
                self.cards.addWidget(card, i // 4, i % 4)
                self.card_labels[code] = card
            shown = "—" if value is None else numerals.format_money(value, 1 if unit == "٪" or unit == "متر" else 0, None)
            self.card_labels[code].setText(numerals.to_persian_digits(f"{title}\n{shown} {unit}"))
        rows = list(self.result.by_type.values())
        self.type_table.setRowCount(len(rows))
        for r, t in enumerate(rows):
            for c, text in enumerate([t.label, str(t.done), str(t.open), "—" if t.avg_minutes is None else str(t.avg_minutes)]):
                self.type_table.setItem(r, c, QTableWidgetItem(numerals.to_persian_digits(text)))
        from peecha.db.base import new_session
        from peecha.db.models.security import User
        from sqlalchemy import select

        with new_session() as session:
            names = dict(session.execute(select(User.user_id, User.full_name)).all())
        ops_rows = sorted(self.result.operators.items(), key=lambda kv: -kv[1].tasks)
        self.operator_table.setRowCount(len(ops_rows))
        for r, (uid, o) in enumerate(ops_rows):
            rate = f"{o.tasks / o.hours:.1f}" if o.hours >= 0.25 else "—"
            acc = f"{o.exact * 100 / o.picks:.0f}٪" if o.picks else "—"
            for c, text in enumerate([names.get(uid, "نامشخص"), str(o.tasks), f"{o.hours:.1f}", rate, str(o.picks), acc]):
                self.operator_table.setItem(r, c, QTableWidgetItem(numerals.to_persian_digits(text)))


class WarehouseOperationsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        title = QLabel("جانمایی، برداشت و برنامهٔ شمارش")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.tabs = QTabWidget()
        self.tasks_tab = _TasksTab()
        self.plans_tab = _PlansTab()
        self.replenish_tab = _ReplenishTab()
        self.waves_tab = _WavesTab()
        self.count_tab = _LocationCountTab()
        self.kpi_tab = _KpiTab()
        self.tabs.addTab(self.tasks_tab, "وظایفِ جانمایی، برداشت و تأمین")
        self.tabs.addTab(self.plans_tab, "برنامهٔ شمارشِ دوره‌ای")
        self.tabs.addTab(self.replenish_tab, "قاعده‌هایِ تأمینِ مجدد")
        self.tabs.addTab(self.waves_tab, "موج‌هایِ برداشت")
        self.tabs.addTab(self.count_tab, "شمارشِ محل")
        self.tabs.addTab(self.kpi_tab, "داشبوردِ عملیات")
        self.tabs.currentChanged.connect(lambda _i: self.tabs.currentWidget().refresh())
        layout.addWidget(self.tabs, stretch=1)

    def refresh(self) -> None:
        self.tasks_tab.refresh()
        self.plans_tab.refresh()
        self.replenish_tab.refresh()
        self.waves_tab.refresh()
        self.count_tab.refresh()
        self.kpi_tab.refresh()
