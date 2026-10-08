"""R294: طراحی فرایند بدون کدنویسی — فهرست فرایندها، ساخت گام‌به‌گام (ویزارد)، طراح گرافیکی، سازندهٔ شرط،
بررسی ایرادها، اجرای آزمایشی و نسخه‌ها. همه روی همان گراف موتور گردش کار کار می‌کنند.
"""

from __future__ import annotations

import copy
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha.services import roles as roles_service
from peecha.services.workflow import builder, conditions, definitions as defs, registry, routing, simulate, sla
from peecha.services.workflow.common import DEFINITION_STATUS, NODE_TYPES, OUTCOMES
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.fixed_assets import P, combo, company_id, fill, num_field, set_combo, table, user_id
from peecha.ui.screens.workflow_center import _ask, _run, _warn, company_user_choices

ms.ICONS.update({
    "ساخت با ویزارد": ("🧙", "primary"), "فرایند خالی": ("🆕", ""), "ویرایش در طراح": ("✏️", ""), "انتشار": ("🚀", ""),
    "فعال‌سازی": ("▶️", ""), "بازگردانی از بایگانی": ("📤", ""), "آزمون و اجرای آزمایشی": ("🧪", ""),
    "کپی فرایند": ("📋", ""), "حذف فرایند": ("🗑️", "danger"), "نسخه‌ها": ("🕘", ""), "ذخیرهٔ پیش‌نویس": ("💾", "primary"),
    "بررسی ایرادها": ("🔍", ""), "چیدمان خودکار": ("🧭", ""), "اتصال دو مرحله": ("🔗", ""),
    "حذف انتخاب‌شده": ("🗑️", "danger"), "ثبت تغییرات این مرحله": ("✔️", "primary"), "بزرگ‌نمایی": ("➕", ""),
    "کوچک‌نمایی": ("➖", ""), "مقایسه با نسخهٔ فعال": ("🔀", ""), "بازگردانی به پیش‌نویس": ("↩️", ""),
    "اجرای آزمایشی": ("▶️", "primary"), "مرحلهٔ قبل": ("▶️", ""), "مرحلهٔ بعد": ("◀️", "primary"),
    "ساخت فرایند": ("✅", "primary"), "افزودن مرحلهٔ تایید": ("➕", ""), "بالا بردن": ("🔼", ""), "پایین بردن": ("🔽", ""),
    "افزودن گیرنده": ("➕", ""), "حذف گیرنده": ("➖", "danger"), "افزودن خانه": ("➕", ""), "حذف خانه": ("➖", "danger"),
    "تنظیم شروع فرایند": ("🚀", ""),
})

NODE_ICONS = {"START": "🚀", "CONDITION": "🔀", "APPROVAL": "🖊️", "TASK": "📋", "ACTION": "⚙️", "NOTIFY": "🔔", "WAIT": "⏳",
              "PARALLEL": "🔱", "JOIN": "🔗", "END": "🏁"}
NODE_COLORS = {"START": "#6366F1", "CONDITION": "#F59E0B", "APPROVAL": "#3B82F6", "TASK": "#14B8A6", "ACTION": "#8B5CF6",
               "NOTIFY": "#0EA5E9", "WAIT": "#64748B", "PARALLEL": "#A855F7", "JOIN": "#A855F7", "END": "#10B981"}
MODES = [("ANY", "اولین تصمیم کافی است"), ("SINGLE", "یک نفر"), ("ALL", "همه باید تایید کنند"),
         ("PERCENT", "درصدی از گیرندگان"), ("SEQUENTIAL", "به ترتیب، یکی پس از دیگری")]
FIELD_KINDS = [("text", "متن"), ("number", "عدد"), ("date", "تاریخ"), ("bool", "بله/خیر"), ("choice", "انتخاب از فهرست")]


def _icon_button(glyph: str, tooltip: str, slot, primary: bool = False) -> QPushButton:
    b = QPushButton(glyph)
    b.setObjectName("primaryIconButton" if primary else "iconButton")
    b.setToolTip(tooltip)
    b.setProperty("label", tooltip)
    b.setFixedWidth(48 if primary else 44)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(lambda _c=False: slot())
    return b


def _btn(label: str, slot) -> QPushButton:
    b = ms.style_button(QPushButton(label))
    b.clicked.connect(lambda _c=False: slot())
    return b


def _sla_choices() -> list[tuple[str, int]]:
    return [(p.name, p.policy_id) for p in sla.list_policies(company_id(), active_only=True)] if company_id() else []


# =========================================================================================================
# گیرندگان (تاییدکننده / مسئول / گیرندهٔ اعلان)
# =========================================================================================================
class SpecListEditor(QWidget):
    changed = Signal()

    def __init__(self, entity_type: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.entity_type = entity_type
        self.specs: list[dict] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMaximumHeight(90)
        layout.addWidget(self.list, stretch=1)
        col = QVBoxLayout()
        col.addWidget(_icon_button("➕", "افزودن گیرنده", self.add_dialog))
        col.addWidget(_icon_button("➖", "حذف گیرنده", self.remove_selected))
        col.addStretch(1)
        layout.addLayout(col)

    def set_specs(self, specs: list[dict]) -> None:
        self.specs = copy.deepcopy(list(specs or []))
        self._redraw()

    def _redraw(self) -> None:
        self.list.clear()
        from peecha.db.base import new_session
        from peecha.services.workflow.common import user_names

        with new_session() as session:
            roles = routing.role_names(session, [s.get("role_id") for s in self.specs])
            users = user_names(session, [s.get("user_id") for s in self.specs])
        for s in self.specs:
            self.list.addItem(routing.describe_spec(s, roles, users))

    def add_spec(self, spec: dict) -> None:
        if spec and spec not in self.specs:
            self.specs.append(copy.deepcopy(spec))
            self._redraw()
            self.changed.emit()

    def remove_selected(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.specs):
            self.specs.pop(row)
            self._redraw()
            self.changed.emit()

    def add_dialog(self) -> None:
        kinds = [(label, kind) for kind, label in routing.KINDS.items() if kind not in ("AMOUNT_TABLE", "RESOLVER")]
        kinds += [(f"مسیریاب: {r.label}", f"RESOLVER:{code}") for code, r in registry.resolvers().items()]
        kind_box = combo(kinds)
        user_box = combo(company_user_choices(), "—")
        role_box = combo([(r.code, r.role_id) for r in roles_service.list_roles(company_id())], "—") if company_id() else combo([])
        adapter = registry.get_adapter(self.entity_type)
        field_box = combo([(f.label, f.key) for f in (adapter.fields if adapter else ()) if f.kind == "user"], "—")
        from peecha.services import hr as hr_service

        unit_box = combo([(u.name, u.org_unit_id) for u in hr_service.list_org_units(company_id())], "—") if company_id() else combo([])
        values = _ask(self, "افزودن گیرنده", [("kind", "چه کسی", kind_box), ("user", "کاربر (برای «کاربر مشخص»)", user_box),
                                             ("role", "نقش (برای «دارندگان یک نقش»)", role_box),
                                             ("field", "فیلد سند (برای «کاربر ثبت‌شده در سند»)", field_box),
                                             ("unit", "واحد سازمانی (برای «مدیر واحد»)", unit_box)])
        if values is None:
            return
        self.add_spec(spec_from(values))


def spec_from(values: dict) -> dict:
    kind = values.get("kind") or ""
    if kind.startswith("RESOLVER:"):
        return {"kind": "RESOLVER", "code": kind.split(":", 1)[1]}
    if kind == "USER":
        return {"kind": "USER", "user_id": values.get("user")} if values.get("user") else {}
    if kind == "ROLE":
        return {"kind": "ROLE", "role_id": values.get("role")} if values.get("role") else {}
    if kind == "FIELD":
        return {"kind": "FIELD", "field": values.get("field")} if values.get("field") else {}
    if kind == "ORG_MANAGER":
        return {"kind": "ORG_MANAGER", "org_unit_id": values.get("unit")} if values.get("unit") else {}
    return {"kind": kind}


# =========================================================================================================
# سازندهٔ شرط
# =========================================================================================================
class _RuleRow(QWidget):
    def __init__(self, builder_widget: "RuleBuilder", leaf: dict | None = None) -> None:
        super().__init__()
        self.rb = builder_widget
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.field = combo([(f.label, f.key) for f in builder_widget.fields])
        self.op = QComboBox()
        self.compare_field = QCheckBox("با فیلد دیگر")
        self.value = QLineEdit()
        self.value_field = combo([(f.label, f.key) for f in builder_widget.fields])
        self.unit = QLabel("")
        for w in (self.field, self.op, self.value, self.value_field, self.unit, self.compare_field):
            layout.addWidget(w)
        layout.addWidget(_icon_button("🗑️", "حذف شرط", lambda: builder_widget.remove_row(self)))
        self.field.currentIndexChanged.connect(lambda _i: self._on_field())
        self.op.currentIndexChanged.connect(lambda _i: self._sync())
        self.compare_field.toggled.connect(lambda _c: self._sync())
        self.value.textChanged.connect(lambda _t: builder_widget.changed.emit())
        self.value_field.currentIndexChanged.connect(lambda _i: builder_widget.changed.emit())
        self._on_field()
        if leaf:
            self.load(leaf)

    def spec(self):
        return self.rb.field_map.get(self.field.currentData())

    def _on_field(self) -> None:
        spec = self.spec()
        current = self.op.currentData()
        self.op.blockSignals(True)
        self.op.clear()
        for op, label in conditions.ops_for(spec.kind if spec else "text"):
            self.op.addItem(label, op)
        idx = self.op.findData(current)
        self.op.setCurrentIndex(idx if idx >= 0 else 0)
        self.op.blockSignals(False)
        self._sync()

    def _sync(self) -> None:
        spec = self.spec()
        unary = self.op.currentData() in ("is_empty", "not_empty", "is_true", "is_false")
        by_field = self.compare_field.isChecked() and not unary
        self.value.setVisible(not unary and not by_field)
        self.value_field.setVisible(by_field)
        self.compare_field.setVisible(not unary)
        is_date = bool(spec and spec.kind == "date")
        self.unit.setText("روز نسبت به امروز (منفی یعنی گذشته)" if is_date and not by_field and not unary else "")
        self.value.setPlaceholderText("مقدار؛ برای «بین» دو عدد با ویرگول" if not is_date else "مثلاً ۰ یعنی امروز")
        self.rb.changed.emit()

    def load(self, leaf: dict) -> None:
        set_combo(self.field, leaf.get("field"))
        self._on_field()
        set_combo(self.op, leaf.get("op"))
        if leaf.get("value_field"):
            self.compare_field.setChecked(True)
            set_combo(self.value_field, leaf["value_field"])
        else:
            v = leaf.get("value")
            if isinstance(v, dict):
                v = v.get("days_from_today", -int(v.get("days_ago", 0)))
            elif isinstance(v, (list, tuple)):
                v = "، ".join(str(x) for x in v)
            self.value.setText(P(v) if v is not None else "")
        self._sync()

    def leaf(self) -> dict | None:
        key, op = self.field.currentData(), self.op.currentData()
        if not key or not op:
            return None
        out = {"field": key, "op": op}
        if op in ("is_empty", "not_empty", "is_true", "is_false"):
            return out
        if self.compare_field.isChecked():
            out["value_field"] = self.value_field.currentData()
            return out
        text = numerals.to_ascii_digits(self.value.text().strip())
        spec = self.spec()
        if spec and spec.kind == "date":
            try:
                out["value"] = {"days_from_today": int(text or "0")}
            except ValueError:
                out["value"] = text
        elif op in ("between", "in", "not_in"):
            out["value"] = [p.strip() for p in text.replace("،", ",").split(",") if p.strip()]
        else:
            out["value"] = text
        return out


class RuleBuilder(QWidget):
    """شرط‌ها روی فیلدهای سند: «همهٔ این شرط‌ها» یا «یکی از این شرط‌ها»، با توضیح فارسی زنده."""

    changed = Signal()

    def __init__(self, entity_type: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[_RuleRow] = []
        self.raw: dict | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.joiner = QComboBox()
        self.joiner.addItem("همهٔ این شرط‌ها برقرار باشد", "all")
        self.joiner.addItem("دست‌کم یکی از این شرط‌ها برقرار باشد", "any")
        self.joiner.currentIndexChanged.connect(lambda _i: self.changed.emit())
        head.addWidget(self.joiner, stretch=1)
        head.addWidget(_icon_button("➕", "افزودن شرط", lambda: self.add_row()))
        layout.addLayout(head)
        self.rows_box = QVBoxLayout()
        layout.addLayout(self.rows_box)
        self.preview = QLabel("")
        self.preview.setObjectName("sectionHint")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        self.changed.connect(self._update_preview)
        self.set_entity(entity_type)

    def set_entity(self, entity_type: str | None) -> None:
        adapter = registry.get_adapter(entity_type)
        self.fields = list(adapter.fields) if adapter else []
        self.field_map = {f.key: f for f in self.fields}
        self.labels = {f.key: f.label for f in self.fields}
        self.set_rule(None)

    def add_row(self, leaf: dict | None = None) -> _RuleRow | None:
        if not self.fields:
            _warn(self, "شرط", "برای این نوع سند فیلدی جهت شرط تعریف نشده است.")
            return None
        row = _RuleRow(self, leaf)
        self.rows.append(row)
        self.rows_box.addWidget(row)
        self.changed.emit()
        return row

    def remove_row(self, row: _RuleRow) -> None:
        if row in self.rows:
            self.rows.remove(row)
            row.setParent(None)
            row.deleteLater()
            self.changed.emit()

    def set_rule(self, rule: dict | None) -> None:
        for row in list(self.rows):
            self.remove_row(row)
        self.raw = None
        if not rule:
            self._update_preview()
            return
        group = "all" if "all" in rule else "any" if "any" in rule else None
        leaves = rule.get(group) if group else [rule]
        if any(not isinstance(x, dict) or "field" not in x for x in leaves or []):
            self.raw = copy.deepcopy(rule)  # قاعدهٔ تودرتو: دست‌نخورده نگه داشته می‌شود
        else:
            set_combo(self.joiner, group or "all")
            for leaf in leaves:
                self.add_row(leaf)
        self._update_preview()

    def rule(self) -> dict | None:
        if self.raw is not None and not self.rows:
            return copy.deepcopy(self.raw)
        leaves = [x for x in (r.leaf() for r in self.rows) if x]
        if not leaves:
            return None
        return leaves[0] if len(leaves) == 1 else {self.joiner.currentData(): leaves}

    def problems(self) -> list[str]:
        return conditions.validate(self.rule(), self.field_map) if self.rule() else []

    def _update_preview(self) -> None:
        rule = self.rule()
        if not rule:
            self.preview.setText("بدون شرط: همیشه برقرار است.")
            return
        issues = self.problems()
        text = "یعنی: " + conditions.describe(rule, self.labels)
        self.preview.setText(P(text + ("\n⚠ " + "، ".join(issues) if issues else "")))


# =========================================================================================================
# اجرای آزمایشی
# =========================================================================================================
class SimulateDialog(QDialog):
    def __init__(self, graph: dict, entity_type: str | None, parent=None) -> None:
        super().__init__(parent)
        self.graph, self.entity_type = graph, entity_type
        self.trace: list[simulate.TraceRow] = []
        self.setWindowTitle("اجرای آزمایشی (بدون هیچ تغییری در اطلاعات)")
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        hint = QLabel("مقادیر نمونه را وارد کنید (یا شمارهٔ یک سند واقعی را) و تصمیم فرضی هر مرحلهٔ تایید را انتخاب کنید.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        adapter = registry.get_adapter(entity_type)
        self.inputs: dict[str, QLineEdit] = {}
        for f in (adapter.fields if adapter else ()):
            w = QLineEdit()
            if f.kind == "date":
                w.setPlaceholderText("روز نسبت به امروز، مثلاً -۵")
            self.inputs[f.key] = w
            form.addRow(f.label, w)
        self.entity_id = QLineEdit()
        self.entity_id.setPlaceholderText("اختیاری")
        form.addRow("شمارهٔ سند واقعی", self.entity_id)
        self.decisions: dict[str, QComboBox] = {}
        for n in graph.get("nodes", []):
            if n.get("type") in ("APPROVAL", "TASK"):
                box = QComboBox()
                for code, label in defs.NODE_EDGE_LABELS[n["type"]].items():
                    box.addItem(label, code)
                self.decisions[n["id"]] = box
                form.addRow(f"تصمیم فرضی «{n.get('label')}»", box)
        layout.addLayout(form)
        layout.addWidget(_btn("اجرای آزمایشی", self.run))
        self.t_trace = table(["", "مرحله", "نتیجه"])
        layout.addWidget(self.t_trace, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _context(self) -> dict:
        import datetime

        adapter = registry.get_adapter(self.entity_type)
        kinds = {f.key: f.kind for f in (adapter.fields if adapter else ())}
        out = {}
        for key, w in self.inputs.items():
            text = numerals.to_ascii_digits(w.text().strip())
            if not text:
                continue
            if kinds.get(key) == "date":
                try:
                    out[key] = datetime.date.today() + datetime.timedelta(days=int(text))
                    continue
                except ValueError:
                    pass
            out[key] = text
        return out

    def run(self, context: dict | None = None, decisions: dict | None = None) -> list:
        ctx = self._context() if context is None else context
        dec = {nid: box.currentData() for nid, box in self.decisions.items()} if decisions is None else decisions
        eid = numerals.to_ascii_digits(self.entity_id.text().strip())
        self.trace = simulate.simulate(company_id(), self.graph, self.entity_type, context=ctx, decisions=dec,
                                       entity_id=int(eid) if eid.isdigit() else None, starter=user_id())
        fill(self.t_trace, [["✔" if t.ok else "✖", t.title, t.result] for t in self.trace])
        for r, t in enumerate(self.trace):
            if not t.ok:
                for c in range(3):
                    self.t_trace.item(r, c).setForeground(QColor("#EF4444"))
        return self.trace


# =========================================================================================================
# ویزارد ساخت فرایند (۸ گام)
# =========================================================================================================
STEPS = ["اطلاعات پایه", "زمان شروع", "شرط شروع", "مراحل تایید", "اقدام‌های پس از تایید", "اعلان‌ها", "رد و اصلاح",
         "بازبینی و آزمون"]


class LevelDialog(QDialog):
    def __init__(self, entity_type: str | None, level: builder.ApprovalLevel | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("مرحلهٔ تایید")
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.label = QLineEdit(level.label if level else "")
        self.approvers = SpecListEditor(entity_type)
        self.approvers.set_specs(level.approvers if level else [])
        self.mode = combo([(label, code) for code, label in MODES])
        set_combo(self.mode, level.mode if level else "ANY")
        self.percent = num_field(level.percent if level and level.percent else 50)
        self.sla = combo(_sla_choices(), "بدون مهلت")
        set_combo(self.sla, level.sla_policy_id if level else None)
        self.allow_changes = QCheckBox("تاییدکننده بتواند درخواست را برای اصلاح برگرداند")
        self.allow_changes.setChecked(bool(level and level.allow_changes))
        self.instructions = QLineEdit(level.instructions if level else "")
        self.only_if = RuleBuilder(entity_type)
        self.only_if.set_rule(level.only_if if level else None)
        for label, w in (("عنوان مرحله", self.label), ("تاییدکنندگان", self.approvers), ("شیوهٔ تایید", self.mode),
                         ("درصد لازم", self.percent), ("مهلت و ارجاع", self.sla), ("راهنما برای تاییدکننده", self.instructions),
                         ("فقط وقتی", self.only_if), ("", self.allow_changes)):
            form.addRow(label, w)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def level(self) -> builder.ApprovalLevel:
        try:
            pct = int(numerals.to_ascii_digits(self.percent.text().strip() or "50"))
        except ValueError:
            pct = 50
        return builder.ApprovalLevel(self.label.text().strip() or "تایید", self.approvers.specs, self.mode.currentData(),
                                     pct if self.mode.currentData() == "PERCENT" else None, self.sla.currentData(),
                                     self.only_if.rule(), self.allow_changes.isChecked(), self.instructions.text().strip())


class WizardDialog(QDialog):
    """ساخت فرایند در ۸ گام ساده؛ نتیجه یک پیش‌نویس است که در طراح هم قابل ویرایش است."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ساخت فرایند گام‌به‌گام")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(820, 620)
        self.dialog_runner = None
        self.created_id: int | None = None
        self.levels: list[builder.ApprovalLevel] = []
        layout = QVBoxLayout(self)
        self.steps_label = QLabel("")
        self.steps_label.setTextFormat(Qt.RichText)
        self.steps_label.setWordWrap(True)
        layout.addWidget(self.steps_label)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, stretch=1)
        for build in (self._p_basic, self._p_trigger, self._p_condition, self._p_levels, self._p_actions, self._p_notify,
                      self._p_reject, self._p_review):
            self.stack.addWidget(build())
        nav = QHBoxLayout()
        self.prev_btn = _btn("مرحلهٔ قبل", self.prev)
        self.next_btn = _btn("مرحلهٔ بعد", self.next)
        self.finish_btn = _btn("ساخت فرایند", self.finish)
        self.publish_now = QCheckBox("پس از ساخت، منتشر و فعال شود")
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        nav.addStretch(1)
        nav.addWidget(self.publish_now)
        nav.addWidget(self.finish_btn)
        layout.addLayout(nav)
        self.go(0)

    # --- گام‌ها -------------------------------------------------------------------------------------------
    def _page(self, hint: str) -> tuple[QWidget, QFormLayout]:
        w = QWidget()
        v = QVBoxLayout(w)
        note = QLabel(hint)
        note.setObjectName("sectionHint")
        note.setWordWrap(True)
        v.addWidget(note)
        form = QFormLayout()
        v.addLayout(form)
        v.addStretch(1)
        return w, form

    def _p_basic(self) -> QWidget:
        w, form = self._page("نام فرایند و نوع سندی که این فرایند برایش اجرا می‌شود را مشخص کنید.")
        self.name = QLineEdit()
        self.code = QLineEdit()
        self.code.setPlaceholderText("کد کوتاه لاتین، مثلاً PO_APPROVAL")
        self.entity = combo([(f"{a.label}", a.entity_type) for a in registry.adapters()], "بدون سند (فرایند عمومی)")
        self.entity.currentIndexChanged.connect(lambda _i: self._on_entity())
        self.description = QLineEdit()
        for label, x in (("نام فرایند", self.name), ("کد", self.code), ("نوع سند", self.entity), ("توضیح", self.description)):
            form.addRow(label, x)
        return w

    def _p_trigger(self) -> QWidget:
        w, form = self._page("فرایند چه زمانی شروع شود؟")
        self.ttype = combo([(label, code) for code, label in builder.TRIGGER_LABELS.items()])
        self.events = QListWidget()
        self.events.setMaximumHeight(140)
        self.every = combo([(label, code) for code, label in builder.EVERY_LABELS.items()])
        self.at = QLineEdit("08:00")
        self.scan = combo([])
        self.ttype.currentIndexChanged.connect(lambda _i: self._sync_trigger())
        for label, x in (("نوع شروع", self.ttype), ("رویدادها", self.events), ("تکرار", self.every), ("ساعت", self.at),
                         ("بررسی دوره‌ای", self.scan)):
            form.addRow(label, x)
        self.trigger_form = form
        return w

    def _p_condition(self) -> QWidget:
        w, form = self._page("اگر فرایند فقط برای بعضی اسناد لازم است (مثلاً مبلغ بیش از ۵۰۰ میلیون ریال)، شرط بگذارید؛ "
                             "وگرنه خالی بگذارید.")
        self.start_rule = RuleBuilder()
        form.addRow(self.start_rule)
        return w

    def _p_levels(self) -> QWidget:
        w, form = self._page("مرحله‌های تایید را به ترتیب اضافه کنید. هر مرحله می‌تواند فقط در شرایط خاص اجرا شود.")
        self.t_levels = table(["مرحله", "تاییدکنندگان", "شیوه", "شرط"])
        form.addRow(self.t_levels)
        row = QHBoxLayout()
        for label, slot in (("افزودن مرحلهٔ تایید", lambda: self.edit_level(new=True)), ("ویرایش مرحله", self.edit_level),
                            ("حذف مرحله", self.remove_level), ("بالا بردن", lambda: self.move_level(-1)),
                            ("پایین بردن", lambda: self.move_level(1))):
            row.addWidget(_btn(label, slot))
        row.addStretch(1)
        form.addRow(row)
        return w

    def _p_actions(self) -> QWidget:
        w, form = self._page("پس از تایید نهایی، کدام کارها خودکار انجام شود؟ (به همین ترتیب)")
        self.actions = QListWidget()
        form.addRow(self.actions)
        return w

    def _p_notify(self) -> QWidget:
        w, form = self._page("چه کسانی از نتیجه باخبر شوند؟")
        self.notify_ok = QCheckBox("پس از تایید نهایی به درخواست‌کننده خبر داده شود")
        self.notify_ok.setChecked(True)
        self.notify_extra = SpecListEditor()
        form.addRow(self.notify_ok)
        form.addRow("گیرندگان بیشتر خبر تایید", self.notify_extra)
        return w

    def _p_reject(self) -> QWidget:
        w, form = self._page("اگر درخواست رد شود چه اتفاقی بیفتد؟ امکان «برگشت برای اصلاح» را در هر مرحلهٔ تایید فعال کنید.")
        self.notify_rej = QCheckBox("علت رد برای درخواست‌کننده فرستاده شود")
        self.notify_rej.setChecked(True)
        self.changes_all = QCheckBox("در همهٔ مرحله‌ها «برگشت برای اصلاح» فعال باشد")
        form.addRow(self.notify_rej)
        form.addRow(self.changes_all)
        return w

    def _p_review(self) -> QWidget:
        w, form = self._page("خلاصهٔ فرایند را بازبینی کنید. اگر ایرادی باشد همین‌جا نشان داده می‌شود.")
        self.summary = QListWidget()
        self.issues = QListWidget()
        form.addRow("خلاصه", self.summary)
        form.addRow("ایرادها", self.issues)
        form.addRow(_btn("آزمون و اجرای آزمایشی", self.test_run))
        return w

    # --- منطق ---------------------------------------------------------------------------------------------
    def _on_entity(self) -> None:
        et = self.entity.currentData()
        self.start_rule.set_entity(et)
        self.events.clear()
        for code, label in registry.event_choices(et):
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, code)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.events.addItem(item)
        self.scan.clear()
        for code, scan in registry.scans().items():
            if scan.entity_type == et:
                self.scan.addItem(scan.label, code)
        self.actions.clear()
        for code, label, risk in registry.action_choices(et):
            item = QListWidgetItem(label + (" (حساس)" if risk == "HIGH" else ""))
            item.setData(Qt.UserRole, code)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.actions.addItem(item)
        for i, level in enumerate(self.levels):
            self.levels[i] = builder.ApprovalLevel(level.label, level.approvers, level.mode, level.percent, level.sla_policy_id,
                                                   None, level.allow_changes, level.instructions)
        self.notify_extra.entity_type = et
        self._sync_trigger()

    def _sync_trigger(self) -> None:
        t = self.ttype.currentData()
        for w, show in ((self.events, t == "EVENT"), (self.every, t == "SCHEDULE"), (self.at, t == "SCHEDULE"),
                        (self.scan, t == "SCAN")):
            w.setVisible(show)
            label = self.trigger_form.labelForField(w)
            if label is not None:
                label.setVisible(show)

    def go(self, index: int) -> None:
        index = max(0, min(index, len(STEPS) - 1))
        if index == len(STEPS) - 1:
            self.refresh_review()
        self.stack.setCurrentIndex(index)
        parts = []
        for i, s in enumerate(STEPS):
            num = numerals.to_persian_digits(str(i + 1))
            style = "font-weight:bold; color:#3B82F6" if i == index else ("color:#10B981" if i < index else "color:#94A3B8")
            parts.append(f"<span style='{style}'>{num}. {s}</span>")
        self.steps_label.setText(" ← ".join(parts))
        self.prev_btn.setEnabled(index > 0)
        self.next_btn.setEnabled(index < len(STEPS) - 1)

    def _step_problem(self, index: int) -> str | None:
        if index == 0:
            if not self.name.text().strip() or not self.code.text().strip():
                return "نام و کد فرایند را وارد کنید."
        if index == 1 and self.ttype.currentData() == "EVENT" and not self._checked(self.events):
            return "دست‌کم یک رویداد را انتخاب کنید."
        if index == 1 and self.ttype.currentData() == "SCAN" and self.scan.currentData() is None:
            return "بررسی دوره‌ای برای این نوع سند تعریف نشده است."
        if index == 2 and self.start_rule.problems():
            return "شرط شروع: " + "، ".join(self.start_rule.problems())
        if index == 3 and not self.levels and not self._checked(self.actions):
            return "دست‌کم یک مرحلهٔ تایید اضافه کنید."
        return None

    def next(self) -> bool:
        problem = self._step_problem(self.stack.currentIndex())
        if problem:
            _warn(self, "ساخت فرایند", problem)
            return False
        self.go(self.stack.currentIndex() + 1)
        return True

    def prev(self) -> None:
        self.go(self.stack.currentIndex() - 1)

    @staticmethod
    def _checked(lst: QListWidget) -> list:
        return [lst.item(i).data(Qt.UserRole) for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked]

    def check_item(self, lst: QListWidget, code: str, on: bool = True) -> None:
        for i in range(lst.count()):
            if lst.item(i).data(Qt.UserRole) == code:
                lst.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def _level_row(self) -> int:
        items = self.t_levels.selectedItems()
        return items[0].row() if items else self.t_levels.currentRow()

    def edit_level(self, new: bool = False, level: builder.ApprovalLevel | None = None) -> bool:
        row = self._level_row()
        if not new and not 0 <= row < len(self.levels):
            _warn(self, "مراحل تایید", "یک مرحله را انتخاب کنید.")
            return False
        if level is None:
            dlg = LevelDialog(self.entity.currentData(), None if new else self.levels[row], self)
            ok = self.dialog_runner(dlg) if self.dialog_runner else dlg.exec() == QDialog.Accepted
            if not ok:
                return False
            level = dlg.level()
        if not level.approvers:
            _warn(self, "مراحل تایید", "دست‌کم یک تاییدکننده انتخاب کنید.")
            return False
        if new:
            self.levels.append(level)
        else:
            self.levels[row] = level
        self._fill_levels()
        return True

    def remove_level(self) -> None:
        row = self._level_row()
        if 0 <= row < len(self.levels):
            self.levels.pop(row)
            self._fill_levels()

    def move_level(self, delta: int) -> None:
        row = self._level_row()
        target = row + delta
        if 0 <= row < len(self.levels) and 0 <= target < len(self.levels):
            self.levels[row], self.levels[target] = self.levels[target], self.levels[row]
            self._fill_levels()
            self.t_levels.setCurrentCell(target, 0)

    def _fill_levels(self) -> None:
        adapter = registry.get_adapter(self.entity.currentData())
        labels = adapter.labels() if adapter else {}
        fill(self.t_levels, [[lv.label, builder._approvers_text(company_id(), lv.approvers), dict(MODES).get(lv.mode, ""),
                              conditions.describe(lv.only_if, labels) if lv.only_if else "همیشه"] for lv in self.levels])

    def spec(self) -> builder.WizardSpec:
        t = self.ttype.currentData()
        trigger = {"type": t}
        if t == "EVENT":
            trigger["events"] = self._checked(self.events)
        elif t == "SCHEDULE":
            trigger.update(every=self.every.currentData(), at=numerals.to_ascii_digits(self.at.text().strip() or "08:00"))
        elif t == "SCAN":
            trigger.update(scan=self.scan.currentData(), every_minutes=60)
        levels = [builder.ApprovalLevel(lv.label, lv.approvers, lv.mode, lv.percent, lv.sla_policy_id, lv.only_if,
                                        lv.allow_changes or self.changes_all.isChecked(), lv.instructions) for lv in self.levels]
        return builder.WizardSpec(self.name.text().strip(), self.code.text().strip(), self.entity.currentData(),
                                  self.description.text().strip(), trigger, self.start_rule.rule(), levels,
                                  self._checked(self.actions), self.notify_ok.isChecked(), self.notify_rej.isChecked(),
                                  self.notify_extra.specs)

    def graph(self) -> dict | None:
        graph, ok = _run(self, "ساخت فرایند", builder.build_graph, self.spec())
        return graph if ok else None

    def refresh_review(self) -> None:
        self.summary.clear()
        self.issues.clear()
        try:
            graph = builder.build_graph(self.spec())
        except ValueError as exc:
            self.issues.addItem(str(exc))
            return
        for line in builder.describe_graph(graph, self.entity.currentData(), company_id()):
            self.summary.addItem(P(line))
        for issue in defs.validate_graph(company_id(), graph, self.entity.currentData()):
            self.issues.addItem(("⛔ " if issue.level == "error" else "⚠ ") + issue.message)
        if not self.issues.count():
            self.issues.addItem("✔ ایرادی پیدا نشد.")

    def test_run(self) -> SimulateDialog | None:
        graph = self.graph()
        if graph is None:
            return None
        dlg = SimulateDialog(graph, self.entity.currentData(), self)
        if self.dialog_runner is None:
            dlg.exec()
        return dlg

    def finish(self) -> int | None:
        for i in range(len(STEPS) - 1):
            problem = self._step_problem(i)
            if problem:
                self.go(i)
                _warn(self, "ساخت فرایند", problem)
                return None
        graph = self.graph()
        if graph is None:
            return None
        spec = self.spec()
        did, ok = _run(self, "ساخت فرایند", defs.create_definition, company_id(), user_id(), code=spec.code, name=spec.name,
                       entity_type=spec.entity_type, description=spec.description or None, graph=graph)
        if not ok:
            return None
        if self.publish_now.isChecked():
            _r, published = _run(self, "انتشار", defs.publish, company_id(), user_id(), did)
            if published:
                _run(self, "فعال‌سازی", defs.set_status, company_id(), user_id(), did, "ACTIVE")
        self.created_id = did
        self.accept()
        return did


# =========================================================================================================
# طراح گرافیکی
# =========================================================================================================
W, H = 180.0, 58.0


class NodeItem(QGraphicsRectItem):
    def __init__(self, designer: "DesignerScreen", node: dict) -> None:
        super().__init__(0, 0, W, H)
        self.designer, self.node_id = designer, node["id"]
        ntype = node.get("type", "START")
        color = QColor(NODE_COLORS.get(ntype, "#64748B"))
        if ntype == "END" and node.get("outcome") == "REJECTED":
            color = QColor("#EF4444")
        self.setBrush(QBrush(color.lighter(185)))
        self.setPen(QPen(color, 2))
        title = QGraphicsSimpleTextItem(f"{NODE_ICONS.get(ntype, '')} {node.get('label') or NODE_TYPES.get(ntype, '')}", self)
        font = QFont()
        font.setBold(True)
        title.setFont(font)
        title.setPos(10, 8)
        sub = QGraphicsSimpleTextItem(NODE_TYPES.get(ntype, "") if ntype != "START" else "شروع فرایند", self)
        sub.setBrush(QBrush(QColor("#475569")))
        sub.setPos(10, 32)
        pos = node.get("pos") or [0, 0]
        self.setPos(float(pos[0]), float(pos[1]))
        # پس از جای‌گذاری اولیه، تا ساختن صحنه «تغییر ذخیره‌نشده» حساب نشود
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)

    def itemChange(self, change, value):  # noqa: N802 -- نام متد Qt
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.designer.node_moved(self.node_id, self.pos())
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self.brush())
        pen = QPen(self.pen())
        if self.isSelected():
            pen.setWidth(4)
            pen.setColor(QColor("#1D4ED8"))
        if self.node_id in self.designer.highlight:
            pen.setColor(QColor("#10B981") if self.designer.highlight[self.node_id] else QColor("#EF4444"))
            pen.setWidth(4)
        painter.setPen(pen)
        painter.drawRoundedRect(self.rect(), 12, 12)


class EdgeItem(QGraphicsPathItem):
    def __init__(self, designer: "DesignerScreen", edge: dict, src: QPointF, dst: QPointF, back: bool) -> None:
        super().__init__()
        self.edge = edge
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        start = QPointF(src.x() + W / 2, src.y() + H)
        end = QPointF(dst.x() + W / 2, dst.y())
        path = QPainterPath(start)
        if back:  # مسیر برگشتی از کنار
            side = max(src.x(), dst.x()) + W + 40
            path.cubicTo(QPointF(side, start.y() + 40), QPointF(side, end.y() - 40), end)
        else:
            mid = (start.y() + end.y()) / 2
            path.cubicTo(QPointF(start.x(), mid), QPointF(end.x(), mid), end)
        prev = path.pointAtPercent(0.96)
        dx, dy = end.x() - prev.x(), end.y() - prev.y()
        length = math.hypot(dx, dy) or 1.0
        ux, uy, size = dx / length, dy / length, 10.0
        left = QPointF(end.x() - ux * size - uy * size * 0.55, end.y() - uy * size + ux * size * 0.55)
        right = QPointF(end.x() - ux * size + uy * size * 0.55, end.y() - uy * size - ux * size * 0.55)
        label_at = path.pointAtPercent(0.45)
        path.addPolygon(QPolygonF([end, left, right, end]))
        self.setPath(path)
        color = {"no": "#EF4444", "rejected": "#EF4444", "failed": "#EF4444", "timeout": "#F59E0B",
                 "changes": "#F59E0B"}.get(edge.get("when") or "", "#475569")
        self.setPen(QPen(QColor(color), 2))
        if edge.get("when"):
            label = QGraphicsSimpleTextItem(defs.EDGE_LABELS.get(edge["when"], edge["when"]), self)
            label.setBrush(QBrush(QColor(color)))
            label.setPos(label_at.x() + 6, label_at.y() - 8)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self.isSelected():
            pen = QPen(self.pen())
            pen.setWidth(4)
            painter.setPen(pen)
            painter.drawPath(self.path())
            return
        super().paint(painter, option, widget)


@ms.styled
class DesignerScreen(QWidget):
    """طراح گرافیکی: مرحله‌ها را از نوار کنار اضافه کنید، با «اتصال» به هم وصل کنید و ویژگی هر مرحله را کنار صفحه تنظیم کنید."""

    scroll_in_mdi = False

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.definition_id: int | None = None
        self.entity_type: str | None = None
        self.graph: dict = defs.empty_graph()
        self.items: dict[str, NodeItem] = {}
        self.highlight: dict[str, bool] = {}
        self.selected_node: str | None = None
        self.selected_edge: dict | None = None
        self.dirty = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        self.title = QLabel("طراح فرایند")
        self.title.setObjectName("pageTitle")
        self.status = QLabel("")
        outer.addWidget(ms.header_card(self.title, self.status))
        split = QSplitter(Qt.Horizontal)
        palette = QWidget()
        pl = QVBoxLayout(palette)
        pl.setContentsMargins(4, 4, 4, 4)
        for ntype in ("CONDITION", "APPROVAL", "TASK", "ACTION", "NOTIFY", "WAIT", "PARALLEL", "JOIN", "END"):
            pl.addWidget(_icon_button(NODE_ICONS[ntype], f"افزودن مرحلهٔ «{NODE_TYPES[ntype]}»", lambda t=ntype: self.add_node(t)))
        pl.addStretch(1)
        split.addWidget(palette)
        self.scene = QGraphicsScene()
        self.scene.selectionChanged.connect(self._on_selection)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.RubberBandDrag)
        split.addWidget(self.view)
        side = QWidget()
        self.side_layout = QVBoxLayout(side)
        self.props_title = QLabel("یک مرحله را انتخاب کنید")
        self.props_title.setObjectName("sectionTitle")
        self.side_layout.addWidget(self.props_title)
        self.props_host = QWidget()
        self.props_form = QFormLayout(self.props_host)
        self.side_layout.addWidget(self.props_host)
        self.apply_btn = _btn("ثبت تغییرات این مرحله", self.apply_properties)
        self.side_layout.addWidget(self.apply_btn)
        issues_title = QLabel("ایرادها")
        issues_title.setObjectName("sectionTitle")
        self.side_layout.addWidget(issues_title)
        self.issues = QListWidget()
        self.issues.itemClicked.connect(self._on_issue_clicked)
        self.side_layout.addWidget(self.issues, stretch=1)
        split.addWidget(side)
        split.setStretchFactor(1, 4)
        split.setStretchFactor(2, 2)
        outer.addWidget(split, stretch=1)
        self.buttons = {k: QPushButton(t) for k, t in (
            ("save", "ذخیرهٔ پیش‌نویس"), ("validate", "بررسی ایرادها"), ("test", "آزمون و اجرای آزمایشی"),
            ("publish", "انتشار"), ("start", "تنظیم شروع فرایند"), ("connect", "اتصال دو مرحله"), ("delete", "حذف انتخاب‌شده"),
            ("layout", "چیدمان خودکار"), ("zoom_in", "بزرگ‌نمایی"), ("zoom_out", "کوچک‌نمایی"))}
        B = self.buttons
        B["save"].clicked.connect(lambda: self.save())
        B["validate"].clicked.connect(lambda: self.validate())
        B["test"].clicked.connect(lambda: self.test_run())
        B["publish"].clicked.connect(lambda: self.publish())
        B["start"].clicked.connect(lambda: self.select_node(defs.START))
        B["connect"].clicked.connect(lambda: self.connect_selected())
        B["delete"].clicked.connect(lambda: self.delete_selected())
        B["layout"].clicked.connect(lambda: self.auto_layout())
        B["zoom_in"].clicked.connect(lambda: self.view.scale(1.15, 1.15))
        B["zoom_out"].clicked.connect(lambda: self.view.scale(1 / 1.15, 1 / 1.15))
        outer.addWidget(ms.footer([[B["save"], B["validate"], B["test"], B["publish"]],
                                   [B["start"], B["connect"], B["delete"], B["layout"]], [B["zoom_in"], B["zoom_out"]]]))

    # --- بارگذاری و ترسیم ------------------------------------------------------------------------------
    def refresh(self) -> None:
        if self.definition_id is not None:
            self._update_status()

    def load(self, definition_id: int) -> None:
        d = defs.get_definition(company_id(), definition_id)
        self.definition_id, self.entity_type = definition_id, d.entity_type
        self.graph = defs.get_graph(company_id(), definition_id)
        if any("pos" not in n for n in self.graph.get("nodes", [])):
            self.graph = builder.auto_layout(self.graph)
        self.title.setText(f"طراح فرایند: {d.name}")
        self.dirty = False
        self.redraw()
        self.validate(show=False)
        self._update_status()

    def _update_status(self) -> None:
        d = defs.get_definition(company_id(), self.definition_id)
        version = f"نسخهٔ فعال: {P(d.active_version_no)}" if d.active_version_no else "هنوز منتشر نشده"
        self.status.setText(P(f"{d.status_label} — {version}" + (" — تغییرات ذخیره‌نشده" if self.dirty else "")))

    def redraw(self) -> None:
        self.scene.blockSignals(True)
        self.scene.clear()
        self.items = {}
        start = {"id": defs.START, "type": "START", "label": "شروع", "pos": (self.graph.get("layout") or {}).get("start", [0, -120])}
        for node in [start] + list(self.graph.get("nodes", [])):
            item = NodeItem(self, node)
            self.scene.addItem(item)
            self.items[node["id"]] = item
        depth = self._depths()
        for e in self.graph.get("edges", []):
            a, b = self.items.get(e["from"]), self.items.get(e["to"])
            if a is None or b is None:
                continue
            back = depth.get(e["to"], 0) <= depth.get(e["from"], 0) and e["from"] != defs.START
            edge = EdgeItem(self, e, a.pos(), b.pos(), back)
            edge.setZValue(-1)
            self.scene.addItem(edge)
        self.scene.blockSignals(False)
        if self.selected_node in self.items:
            self.items[self.selected_node].setSelected(True)

    def _depths(self) -> dict[str, int]:
        depth = {defs.START: 0}
        queue = [defs.START]
        while queue:
            nid = queue.pop(0)
            for e in defs.outgoing(self.graph, nid):
                if e["to"] not in depth:
                    depth[e["to"]] = depth[nid] + 1
                    queue.append(e["to"])
        return depth

    def node_moved(self, node_id: str, pos: QPointF) -> None:
        if node_id == defs.START:
            self.graph.setdefault("layout", {})["start"] = [pos.x(), pos.y()]
        else:
            node = defs.nodes_by_id(self.graph).get(node_id)
            if node is not None:
                node["pos"] = [pos.x(), pos.y()]
        self.dirty = True

    # --- انتخاب و ویژگی‌ها --------------------------------------------------------------------------------
    def _on_selection(self) -> None:
        sel = self.scene.selectedItems()
        nodes = [i for i in sel if isinstance(i, NodeItem)]
        edges = [i for i in sel if isinstance(i, EdgeItem)]
        if nodes:
            self.selected_node, self.selected_edge = nodes[-1].node_id, None
        elif edges:
            self.selected_node, self.selected_edge = None, edges[-1].edge
        else:
            return
        self._build_properties()

    def select_node(self, node_id: str) -> None:
        self.selected_node, self.selected_edge = node_id, None
        self.scene.blockSignals(True)
        for nid, item in self.items.items():
            item.setSelected(nid == node_id)
        self.scene.blockSignals(False)
        self._build_properties()

    def select_edge(self, src: str, dst: str) -> None:
        self.selected_node = None
        self.selected_edge = next((e for e in self.graph.get("edges", []) if e["from"] == src and e["to"] == dst), None)
        self._build_properties()

    def _clear_form(self) -> None:
        while self.props_form.rowCount():
            self.props_form.removeRow(0)
        self.w: dict[str, QWidget] = {}

    def _row(self, key: str, label: str, widget: QWidget) -> QWidget:
        self.w[key] = widget
        self.props_form.addRow(label, widget)
        return widget

    def _build_properties(self) -> None:
        self._clear_form()
        if self.selected_edge is not None:
            e = self.selected_edge
            self.props_title.setText("مسیر")
            box = combo([(label, code) for code, label in builder.edge_choices(self.graph, e["from"])])
            set_combo(box, e.get("when"))
            self._row("when", "نتیجه‌ای که از این مسیر می‌رود", box)
            return
        nid = self.selected_node
        if nid is None:
            self.props_title.setText("یک مرحله را انتخاب کنید")
            return
        if nid == defs.START:
            self._build_trigger_form()
            return
        node = defs.nodes_by_id(self.graph).get(nid) or {}
        t = node.get("type")
        self.props_title.setText(f"{NODE_ICONS.get(t, '')} {NODE_TYPES.get(t, '')}")
        self._row("label", "عنوان", QLineEdit(node.get("label") or ""))
        adapter = registry.get_adapter(self.entity_type)
        if t == "CONDITION":
            rb = RuleBuilder(self.entity_type)
            rb.set_rule(node.get("rule"))
            self._row("rule", "شرط", rb)
        elif t in ("APPROVAL", "TASK"):
            specs = SpecListEditor(self.entity_type)
            specs.set_specs(node.get("approvers" if t == "APPROVAL" else "assignees") or [])
            self._row("specs", "تاییدکنندگان" if t == "APPROVAL" else "مسئولان", specs)
            modes = MODES if t == "APPROVAL" else [("ANY", "یک نفر کافی است"), ("ALL", "همه باید انجام دهند")]
            mode = combo([(label, code) for code, label in modes])
            set_combo(mode, node.get("mode") or "ANY")
            self._row("mode", "شیوه", mode)
            if t == "APPROVAL":
                self._row("percent", "درصد لازم", num_field(node.get("percent") or 50))
            sla_box = combo(_sla_choices(), "بدون مهلت")
            set_combo(sla_box, node.get("sla_policy_id"))
            self._row("sla", "مهلت و ارجاع", sla_box)
            self._row("timeout_hours", "پایان مهلت پس از (ساعت، اختیاری)", num_field(node.get("timeout_hours")))
            self._row("instructions", "راهنما", QLineEdit(node.get("instructions") or ""))
            if t == "APPROVAL":
                for key, label, default in (("allow_delegate", "امکان واگذاری به همکار", True),
                                            ("require_comment_on_reject", "نوشتن علت رد الزامی باشد", True),
                                            ("distinct_approvers", "تاییدکنندهٔ مراحل قبل دوباره تایید نکند", False)):
                    box = QCheckBox(label)
                    box.setChecked(bool(node.get(key, default)))
                    self._row(key, "", box)
            else:
                self._row("fields", "خانه‌های فرم کار", self._fields_editor(node.get("fields") or []))
        elif t == "ACTION":
            box = combo([(label + (" (حساس)" if risk == "HIGH" else ""), code)
                         for code, label, risk in registry.action_choices(self.entity_type)], "—")
            set_combo(box, node.get("action"))
            self._row("action", "اقدام", box)
            spec = registry.find_action(self.entity_type, node.get("action") or "")
            for p in (spec.params if spec else ()):
                self._row(f"param:{p.key}", p.label, QLineEdit(str((node.get("params") or {}).get(p.key, p.default or ""))))
            self._row("retry", "دفعات تلاش دوباره در خطای موقت", num_field((node.get("retry") or {}).get("max", 3)))
        elif t == "NOTIFY":
            specs = SpecListEditor(self.entity_type)
            specs.set_specs(node.get("to") or [])
            self._row("specs", "گیرندگان", specs)
            self._row("title", "عنوان پیام", QLineEdit(node.get("title") or ""))
            body = QTextEdit(node.get("body") or "")
            body.setMaximumHeight(70)
            self._row("body", "متن پیام", body)
            hint = QLabel("می‌توانید {عنوان} یا نام فیلدهای سند را داخل {} بنویسید، مثلاً {" +
                          (adapter.fields[0].label if adapter and adapter.fields else "مبلغ") + "}.")
            hint.setWordWrap(True)
            hint.setObjectName("sectionHint")
            self.props_form.addRow(hint)
        elif t == "WAIT":
            self._row("hours", "چند ساعت", num_field(node.get("hours")))
            self._row("days", "چند روز", num_field(node.get("days")))
            dates = combo([(f.label, f.key) for f in (adapter.fields if adapter else ()) if f.kind == "date"], "—")
            set_combo(dates, node.get("until_field"))
            self._row("until_field", "یا تا تاریخ ثبت‌شده در", dates)
            events = combo([(label, code) for code, label in registry.event_choices(self.entity_type)], "—")
            set_combo(events, node.get("until_event"))
            self._row("until_event", "یا تا رخ دادن رویداد", events)
            self._row("timeout_hours", "حداکثر انتظار برای رویداد (ساعت)", num_field(node.get("timeout_hours")))
        elif t == "END":
            box = combo([(label, code) for code, label in OUTCOMES.items()])
            set_combo(box, node.get("outcome") or "DONE")
            self._row("outcome", "نتیجه", box)

    def _fields_editor(self, fields: list[dict]) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        t = QTableWidget(0, 4)
        t.setHorizontalHeaderLabels(["کلید لاتین", "عنوان", "نوع", "الزامی"])
        t.setMaximumHeight(130)

        def add(f: dict | None = None) -> None:
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, QTableWidgetItem((f or {}).get("key", "")))
            t.setItem(r, 1, QTableWidgetItem((f or {}).get("label", "")))
            kind = combo([(label, code) for code, label in FIELD_KINDS])
            set_combo(kind, (f or {}).get("kind", "text"))
            t.setCellWidget(r, 2, kind)
            req = QTableWidgetItem()
            req.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            req.setCheckState(Qt.Checked if (f or {}).get("required") else Qt.Unchecked)
            t.setItem(r, 3, req)

        for f in fields:
            add(f)
        row = QHBoxLayout()
        row.addWidget(_icon_button("➕", "افزودن خانه", lambda: add()))
        row.addWidget(_icon_button("➖", "حذف خانه", lambda: t.removeRow(t.currentRow()) if t.currentRow() >= 0 else None))
        row.addStretch(1)
        lay.addWidget(t)
        lay.addLayout(row)
        box.table = t
        box.add = add
        return box

    def _build_trigger_form(self) -> None:
        trigger = self.graph.get("trigger") or {}
        self.props_title.setText("🚀 شروع فرایند")
        ttype = combo([(label, code) for code, label in builder.TRIGGER_LABELS.items()])
        set_combo(ttype, trigger.get("type") or "MANUAL")
        self._row("ttype", "نوع شروع", ttype)
        events = QListWidget()
        events.setMaximumHeight(120)
        for code, label in registry.event_choices(self.entity_type):
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, code)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if code in (trigger.get("events") or []) else Qt.Unchecked)
            events.addItem(item)
        self._row("events", "رویدادها", events)
        every = combo([(label, code) for code, label in builder.EVERY_LABELS.items()])
        set_combo(every, trigger.get("every") or "DAY")
        self._row("every", "تکرار (زمان‌بندی)", every)
        self._row("at", "ساعت", QLineEdit(trigger.get("at") or "08:00"))
        scan = combo([(s.label, c) for c, s in registry.scans().items() if s.entity_type == self.entity_type], "—")
        set_combo(scan, trigger.get("scan"))
        self._row("scan", "بررسی دوره‌ای", scan)
        rb = RuleBuilder(self.entity_type)
        rb.set_rule(trigger.get("condition"))
        self._row("condition", "شرط شروع", rb)

    def apply_properties(self) -> bool:
        w = getattr(self, "w", {})
        if self.selected_edge is not None:
            e = self.selected_edge
            when = w["when"].currentData()
            if when:
                e["when"] = when
            else:
                e.pop("when", None)
            return self._changed()
        if self.selected_node == defs.START:
            t = w["ttype"].currentData()
            trigger = {"type": t}
            if t == "EVENT":
                lst = w["events"]
                trigger["events"] = [lst.item(i).data(Qt.UserRole) for i in range(lst.count())
                                     if lst.item(i).checkState() == Qt.Checked]
            elif t == "SCHEDULE":
                trigger.update(every=w["every"].currentData(), at=numerals.to_ascii_digits(w["at"].text().strip() or "08:00"))
            elif t == "SCAN":
                trigger.update(scan=w["scan"].currentData(), every_minutes=60)
            if w["condition"].rule():
                trigger["condition"] = w["condition"].rule()
            self.graph["trigger"] = trigger
            return self._changed()
        node = defs.nodes_by_id(self.graph).get(self.selected_node or "")
        if node is None:
            return False
        t = node["type"]
        node["label"] = w["label"].text().strip() or NODE_TYPES.get(t, "")

        def num(key):
            text = numerals.to_ascii_digits(w[key].text().strip()) if key in w else ""
            try:
                return float(text) if text else None
            except ValueError:
                return None

        def put(key, value):
            if value in (None, "", []):
                node.pop(key, None)
            else:
                node[key] = value

        if t == "CONDITION":
            put("rule", w["rule"].rule())
        elif t in ("APPROVAL", "TASK"):
            node["approvers" if t == "APPROVAL" else "assignees"] = w["specs"].specs
            node["mode"] = w["mode"].currentData()
            if t == "APPROVAL":
                put("percent", int(num("percent") or 50) if node["mode"] == "PERCENT" else None)
                for key in ("allow_delegate", "require_comment_on_reject", "distinct_approvers"):
                    node[key] = w[key].isChecked()
            else:
                table_w = w["fields"].table
                fields = []
                for r in range(table_w.rowCount()):
                    key = (table_w.item(r, 0).text() if table_w.item(r, 0) else "").strip()
                    label = (table_w.item(r, 1).text() if table_w.item(r, 1) else "").strip()
                    if key or label:
                        fields.append({"key": key, "label": label, "kind": table_w.cellWidget(r, 2).currentData(),
                                       "required": table_w.item(r, 3).checkState() == Qt.Checked})
                put("fields", fields)
            put("sla_policy_id", w["sla"].currentData())
            put("timeout_hours", num("timeout_hours"))
            put("instructions", w["instructions"].text().strip())
        elif t == "ACTION":
            node["action"] = w["action"].currentData() or ""
            params = {k.split(":", 1)[1]: v.text().strip() for k, v in w.items() if k.startswith("param:") and v.text().strip()}
            put("params", params)
            node["retry"] = {"max": int(num("retry") or 0), "backoff_minutes": 5}
        elif t == "NOTIFY":
            node["to"] = w["specs"].specs
            node["title"] = w["title"].text().strip()
            put("body", w["body"].toPlainText().strip())
        elif t == "WAIT":
            for key in ("hours", "days", "timeout_hours"):
                put(key, num(key))
            put("until_field", w["until_field"].currentData())
            put("until_event", w["until_event"].currentData())
        elif t == "END":
            node["outcome"] = w["outcome"].currentData()
        return self._changed()

    def _changed(self) -> bool:
        self.dirty = True
        keep_node, keep_edge = self.selected_node, self.selected_edge
        self.redraw()
        self.selected_node, self.selected_edge = keep_node, keep_edge
        self.validate(show=False)
        if self.definition_id is not None:
            self._update_status()
        return True

    # --- ویرایش ساختار ---------------------------------------------------------------------------------
    def add_node(self, node_type: str) -> str:
        center = self.view.mapToScene(self.view.viewport().rect().center())
        nid = builder.add_node(self.graph, node_type, (center.x() - W / 2, center.y() - H / 2))
        self.selected_node = nid
        self._changed()
        self.select_node(nid)
        return nid

    def connect_nodes(self, src: str, dst: str, when: str | None = None) -> bool:
        _r, ok = _run(self, "اتصال", builder.connect, self.graph, src, dst, when)
        if ok:
            self._changed()
        return ok

    def connect_selected(self, when: str | None = None) -> bool:
        nodes = [i.node_id for i in self.scene.selectedItems() if isinstance(i, NodeItem)]
        if len(nodes) != 2:
            _warn(self, "اتصال", "دو مرحله را انتخاب کنید (با نگه‌داشتن Ctrl)؛ اولی مبدأ و دومی مقصد است.")
            return False
        src, dst = nodes[0], nodes[1]
        choices = builder.edge_choices(self.graph, src)
        if when is None and len(choices) > 1:
            values = _ask(self, "اتصال", [("when", "کدام نتیجه به این مسیر برود؟", combo([(l, c) for c, l in choices]))])
            if values is None:
                return False
            when = values["when"]
        elif when is None:
            when = choices[0][0]
        return self.connect_nodes(src, dst, when)

    def delete_selected(self) -> bool:
        if self.selected_edge is not None:
            self.graph["edges"] = [e for e in self.graph.get("edges", []) if e is not self.selected_edge]
            self.selected_edge = None
            return self._changed()
        if self.selected_node and self.selected_node != defs.START:
            builder.remove_node(self.graph, self.selected_node)
            self.selected_node = None
            self._clear_form()
            return self._changed()
        return False

    def auto_layout(self) -> None:
        self.graph = builder.auto_layout(self.graph)
        self._changed()

    # --- بررسی، آزمون، ذخیره، انتشار ----------------------------------------------------------------------
    def validate(self, show: bool = True) -> list:
        issues = defs.validate_graph(company_id(), self.graph, self.entity_type)
        self.issues.clear()
        for i in issues:
            item = QListWidgetItem(("⛔ " if i.level == "error" else "⚠ ") + i.message)
            item.setData(Qt.UserRole, i.node_id)
            self.issues.addItem(item)
        if not issues:
            self.issues.addItem("✔ ایرادی پیدا نشد؛ آمادهٔ انتشار است.")
        return issues

    def _on_issue_clicked(self, item: QListWidgetItem) -> None:
        nid = item.data(Qt.UserRole)
        if nid and nid in self.items:
            self.select_node(nid)
            self.view.centerOn(self.items[nid])

    def test_run(self, context: dict | None = None, decisions: dict | None = None) -> list:
        dlg = SimulateDialog(self.graph, self.entity_type, self)
        if context is not None or decisions is not None:
            trace = dlg.run(context or {}, decisions or {})
        else:
            dlg.exec()
            trace = dlg.trace
        self.highlight = {t.node_id: t.ok for t in trace if t.node_id}
        self.redraw()
        return trace

    def save(self) -> bool:
        if self.definition_id is None:
            return False
        _r, ok = _run(self, "ذخیره", defs.save_draft, company_id(), user_id(), self.definition_id, self.graph)
        if ok:
            self.dirty = False
            self._update_status()
        return ok

    def publish(self) -> bool:
        if not self.save():
            return False
        _r, ok = _run(self, "انتشار", defs.publish, company_id(), user_id(), self.definition_id)
        if ok:
            self._update_status()
        return ok


# =========================================================================================================
# نسخه‌ها
# =========================================================================================================
class VersionsDialog(QDialog):
    def __init__(self, definition_id: int, parent=None) -> None:
        super().__init__(parent)
        self.definition_id = definition_id
        self.setWindowTitle("نسخه‌های فرایند")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(640, 420)
        layout = QVBoxLayout(self)
        self.t = table(["نسخه", "وضعیت", "تاریخ انتشار", "یادداشت"])
        layout.addWidget(self.t, stretch=1)
        self.diff = QListWidget()
        self.diff.setMaximumHeight(120)
        layout.addWidget(self.diff)
        row = QHBoxLayout()
        row.addWidget(_btn("مقایسه با نسخهٔ فعال", self.compare))
        row.addWidget(_btn("بازگردانی به پیش‌نویس", self.restore))
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.reload()

    def reload(self) -> None:
        from peecha.ui.screens.workflow_center import _dt

        self.rows = defs.list_versions(company_id(), self.definition_id)
        status = {"DRAFT": "پیش‌نویس", "PUBLISHED": "منتشرشده (فعال)", "SUPERSEDED": "نسخهٔ قبلی"}
        fill(self.t, [[r.version_no, status.get(r.status_code, r.status_code), _dt(r.published_at), r.notes or ""] for r in self.rows],
             [r.version_id for r in self.rows])

    def _selected(self):
        items = self.t.selectedItems()
        if not items:
            _warn(self, "نسخه‌ها", "یک نسخه را انتخاب کنید.")
            return None
        vid = self.t.item(items[0].row(), 0).data(Qt.UserRole)
        return next(r for r in self.rows if r.version_id == vid)

    def compare(self) -> list[str]:
        row = self._selected()
        if row is None:
            return []
        d = defs.get_definition(company_id(), self.definition_id)
        active = defs.get_graph(company_id(), self.definition_id, d.active_version_id) if d.active_version_id else {}
        lines = builder.diff_graphs(active, row.graph or {})
        self.diff.clear()
        for line in lines:
            self.diff.addItem(line)
        return lines

    def restore(self) -> bool:
        row = self._selected()
        if row is None:
            return False
        _r, ok = _run(self, "نسخه‌ها", defs.save_draft, company_id(), user_id(), self.definition_id, row.graph or {},
                      f"بازگردانی نسخهٔ {row.version_no}")
        if ok:
            self.reload()
        return ok


# =========================================================================================================
# فهرست فرایندها
# =========================================================================================================
@ms.styled
class ProcessListScreen(QWidget):
    scroll_in_mdi = True

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.dialog_runner = None
        self.rows: list[defs.DefinitionRow] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        title = QLabel("فرایندها و طراحی")
        title.setObjectName("pageTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو در نام فرایند…")
        self.search.textChanged.connect(lambda _t: self._fill())
        self.status_filter = QComboBox()
        self.status_filter.addItem("همهٔ وضعیت‌ها", None)
        for code, label in DEFINITION_STATUS.items():
            self.status_filter.addItem(label, code)
        self.status_filter.currentIndexChanged.connect(lambda _i: self._fill())
        outer.addWidget(ms.header_card(title, self.search, self.status_filter))
        cards, self.cards = ms.summary([("all", "همهٔ فرایندها", "info", "🔀"), ("active", "فعال", "success", "▶️"),
                                        ("draft", "در دست طراحی", "warning", "✏️"), ("running", "اجراهای باز", "neutral", "⏳")])
        outer.addWidget(cards)
        self.table = table(["نام", "کد", "نوع سند", "شروع", "وضعیت", "نسخهٔ فعال", "پیش‌نویس تازه", "اجراهای باز"])
        self.table.cellDoubleClicked.connect(lambda _r, _c: self.open_designer())
        outer.addWidget(self.table, stretch=1)
        self.buttons = {k: QPushButton(t) for k, t in (
            ("wizard", "ساخت با ویزارد"), ("blank", "فرایند خالی"), ("design", "ویرایش در طراح"), ("test", "آزمون و اجرای آزمایشی"),
            ("publish", "انتشار"), ("activate", "فعال‌سازی"), ("pause", "توقف"), ("archive", "بایگانی"),
            ("unarchive", "بازگردانی از بایگانی"), ("copy", "کپی فرایند"), ("versions", "نسخه‌ها"), ("delete", "حذف فرایند"),
            ("refresh", "تازه‌سازی"))}
        B = self.buttons
        B["wizard"].clicked.connect(lambda: self.new_with_wizard())
        B["blank"].clicked.connect(lambda: self.new_blank())
        B["design"].clicked.connect(lambda: self.open_designer())
        B["test"].clicked.connect(lambda: self.test())
        B["publish"].clicked.connect(lambda: self.lifecycle("PUBLISHED"))
        B["activate"].clicked.connect(lambda: self.lifecycle("ACTIVE"))
        B["pause"].clicked.connect(lambda: self.lifecycle("PAUSED"))
        B["archive"].clicked.connect(lambda: self.lifecycle("ARCHIVED"))
        B["unarchive"].clicked.connect(lambda: self.lifecycle("DRAFT"))
        B["copy"].clicked.connect(lambda: self.duplicate())
        B["versions"].clicked.connect(lambda: self.versions())
        B["delete"].clicked.connect(lambda: self.delete())
        B["refresh"].clicked.connect(lambda: self.reload())
        outer.addWidget(ms.footer([[B["wizard"], B["blank"], B["design"], B["test"]],
                                   [B["publish"], B["activate"], B["pause"], B["archive"], B["unarchive"]],
                                   [B["copy"], B["versions"], B["delete"], B["refresh"]]]))

    def refresh(self) -> None:
        self.reload()

    def reload(self) -> None:
        if company_id() is None:
            return
        self.rows = defs.list_definitions(company_id())
        self.cards["all"].setText(P(len(self.rows)))
        self.cards["active"].setText(P(sum(1 for r in self.rows if r.status_code in ("ACTIVE", "PUBLISHED"))))
        self.cards["draft"].setText(P(sum(1 for r in self.rows if r.status_code in ("DRAFT", "TESTING"))))
        self.cards["running"].setText(P(sum(r.running for r in self.rows)))
        self._fill()

    def _fill(self) -> None:
        text, status = self.search.text().strip(), self.status_filter.currentData()
        shown = [r for r in self.rows if (not status or r.status_code == status) and (not text or text in r.name or text in r.code)]
        labels = {a.entity_type: a.label for a in registry.adapters()}
        fill(self.table, [[r.name, r.code, labels.get(r.entity_type, "عمومی") if r.entity_type else "عمومی",
                           builder.TRIGGER_LABELS.get(r.trigger_type or "MANUAL", ""), r.status_label,
                           r.active_version_no or "—", "دارد" if r.has_draft and r.active_version_no else "",
                           r.running] for r in shown], [r.definition_id for r in shown])

    def _selected(self) -> int | None:
        items = self.table.selectedItems()
        if not items:
            _warn(self, "فرایندها", "یک فرایند را انتخاب کنید.")
            return None
        return self.table.item(items[0].row(), 0).data(Qt.UserRole)

    def select_definition(self, definition_id: int) -> bool:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == definition_id:
                self.table.setCurrentCell(r, 0)
                return True
        return False

    def new_with_wizard(self) -> int | None:
        dlg = WizardDialog(self)
        if self.dialog_runner is not None:
            self.dialog_runner(dlg)
        else:
            dlg.exec()
        self.reload()
        return dlg.created_id

    def new_blank(self, values: dict | None = None) -> int | None:
        if values is None:
            values = _ask(self, "فرایند خالی", [("name", "نام", QLineEdit()), ("code", "کد لاتین", QLineEdit()),
                                                ("entity_type", "نوع سند", combo([(a.label, a.entity_type) for a in registry.adapters()],
                                                                                 "بدون سند (فرایند عمومی)"))])
            if values is None:
                return None
        did, ok = _run(self, "فرایند تازه", defs.create_definition, company_id(), user_id(), code=values.get("code") or "",
                       name=values.get("name") or "", entity_type=values.get("entity_type"))
        if ok:
            self.reload()
            self.select_definition(did)
            self.open_designer()
        return did

    def open_designer(self) -> DesignerScreen | None:
        did = self._selected()
        if did is None:
            return None
        if self._main_window is not None:
            self._main_window.open_screen("WF_DESIGNER", then=lambda s: s.load(did))
            return None
        screen = DesignerScreen()
        screen.load(did)
        return screen

    def lifecycle(self, status: str) -> bool:
        did = self._selected()
        if did is None:
            return False
        _r, ok = _run(self, "وضعیت فرایند", defs.set_status, company_id(), user_id(), did, status)
        if ok:
            self.reload()
            self.select_definition(did)
        return ok

    def test(self) -> SimulateDialog | None:
        did = self._selected()
        if did is None:
            return None
        d = defs.get_definition(company_id(), did)
        if d.status_code == "DRAFT":
            _r, ok = _run(self, "آزمون", defs.set_status, company_id(), user_id(), did, "TESTING")
            if not ok:
                return None
        dlg = SimulateDialog(defs.get_graph(company_id(), did), d.entity_type, self)
        if self.dialog_runner is None:
            dlg.exec()
        self.reload()
        return dlg

    def duplicate(self, code: str | None = None, name: str | None = None) -> int | None:
        did = self._selected()
        if did is None:
            return None
        src = defs.get_definition(company_id(), did)
        if code is None:
            values = _ask(self, "کپی فرایند", [("code", "کد تازه", QLineEdit(f"{src.code}_2")),
                                               ("name", "نام تازه", QLineEdit(f"{src.name} (کپی)"))])
            if values is None:
                return None
            code, name = values.get("code") or "", values.get("name") or ""
        new_id, ok = _run(self, "کپی فرایند", defs.duplicate, company_id(), user_id(), did, code, name)
        if ok:
            self.reload()
        return new_id

    def versions(self) -> VersionsDialog | None:
        did = self._selected()
        if did is None:
            return None
        dlg = VersionsDialog(did, self)
        if self.dialog_runner is None:
            dlg.exec()
        return dlg

    def delete(self) -> bool:
        did = self._selected()
        if did is None:
            return False
        confirm = getattr(self, "confirm", None)
        question = "فرایند انتخاب‌شده حذف شود؟ (فرایندی که سابقهٔ اجرا دارد فقط بایگانی می‌شود)"
        if confirm is not None:
            if not confirm(question):
                return False
        else:
            from PySide6.QtWidgets import QMessageBox

            if QMessageBox.question(self, "حذف فرایند", question) != QMessageBox.Yes:
                return False
        _r, ok = _run(self, "حذف فرایند", defs.delete_definition, company_id(), user_id(), did)
        if ok:
            self.reload()
        return ok
