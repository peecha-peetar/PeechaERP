"""نوار گردش کار داخل فرم اسناد (R295): مسیر تایید، «ارسال برای تایید» و تاریخچه.

فقط وقتی دیده می‌شود که برای این نوع سند فرایندی فعال باشد یا سند در گردش کار باشد؛ در غیر این صورت فرم دقیقاً مثل
قبل است. guard() پیش از عملیات چندمرحله‌ای (مثل ثبت نهایی) قفل تایید را بررسی می‌کند تا هیچ کاری نیمه‌کاره نماند.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from peecha import numerals
from peecha.services.workflow import definitions, model_events, registry, runtime
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.fixed_assets import FormDialog, combo, company_id, fill, table, user_id

ms.ICONS.update({"ارسال برای تایید": ("📨", "primary"), "تاریخچهٔ گردش کار": ("🕘", "")})

_GLYPH = {"done": "✔", "current": "●", "pending": "○", "failed": "✖"}
_COLOR = {"done": "#10B981", "current": "#3B82F6", "pending": "#94A3B8", "failed": "#EF4444"}


def path_html(path: list[tuple[str, str]]) -> str:
    return " ← ".join(f"<span style='color:{_COLOR.get(state, '#94A3B8')}'>{_GLYPH.get(state, '○')} {label}</span>"
                      for label, state in path)


class TimelineDialog(QDialog):
    def __init__(self, title: str, instance_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(760, 420)
        layout = QVBoxLayout(self)
        self.table = table(["زمان", "مرحله", "نتیجه", "انجام‌دهنده"])
        layout.addWidget(self.table)
        rows = runtime.timeline(company_id(), instance_id)
        fill(self.table, [[numerals.format_jalali_datetime(r.at) if r.at else "—", r.title, r.detail, r.actor] for r in rows])


class WorkflowBar(QWidget):
    """یک ردیف کارت بالای فرم سند. set_entity پس از بارگذاری/ذخیرهٔ سند صدا زده می‌شود."""

    def __init__(self, entity_type: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.entity_type = entity_type
        self.entity_id: int | None = None
        self.instance_id: int | None = None
        self.dialog_runner = None  # برای تست: اجرای دیالوگ بدون نمایش
        self.on_started = None  # پس از ارسال (مثلاً بارگذاری دوبارهٔ سند)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("گردش کار:")
        self.title.setObjectName("sectionHint")
        self.path = QLabel("")
        self.path.setTextFormat(Qt.RichText)
        self.path.setWordWrap(True)
        self.send_button = QPushButton("ارسال برای تایید")
        self.send_button.clicked.connect(self.send)
        self.history_button = QPushButton("تاریخچهٔ گردش کار")
        self.history_button.clicked.connect(self.history)
        for b in (self.send_button, self.history_button):
            ms.style_button(b)
        outer.addWidget(ms.header_card(self.title, self.path, self.send_button, self.history_button))
        self.setVisible(False)

    # --- وضعیت ---------------------------------------------------------------------------------------------
    def set_entity(self, entity_type: str | None, entity_id: int | None) -> None:
        self.entity_type, self.entity_id = entity_type or self.entity_type, entity_id
        self.refresh()

    def _manual(self):
        cid = company_id()
        if not cid or not self.entity_type or registry.get_adapter(self.entity_type) is None:
            return []
        return definitions.manual_definitions(cid, self.entity_type)

    def refresh(self) -> None:
        cid = company_id()
        if not cid or not self.entity_type or not self.entity_id:
            self.instance_id = None
            self.setVisible(False)
            return
        try:
            rows = runtime.list_instances(cid, entity_type=self.entity_type, entity_id=int(self.entity_id), limit=1)
            manual = self._manual()
        except Exception:  # noqa: BLE001 -- نوار کمکی نباید بارگذاری فرم را متوقف کند
            self.setVisible(False)
            return
        self.instance_id = rows[0].instance_id if rows else None
        running = bool(rows) and rows[0].status_code in ("RUNNING", "WAITING")
        if rows:
            self.path.setText(path_html(runtime.status_path(cid, rows[0].instance_id)))
            self.path.setToolTip(f"{rows[0].definition_name} — {rows[0].status_label}")
        else:
            self.path.setText("<span style='color:#94A3B8'>هنوز برای تایید فرستاده نشده است.</span>")
            self.path.setToolTip("")
        self.send_button.setEnabled(bool(manual) and not running)
        self.history_button.setEnabled(self.instance_id is not None)
        self.setVisible(bool(rows) or bool(manual))

    # --- کارها -----------------------------------------------------------------------------------------------
    def send(self) -> bool:
        manual = self._manual()
        if not manual or not self.entity_id:
            return False
        definition_id = manual[0].definition_id
        if len(manual) > 1:
            box = combo([(d.name, d.definition_id) for d in manual])
            dlg = FormDialog("ارسال برای تایید", [("definition", "فرایند", box)], "فرایند تایید را انتخاب کنید.", self)
            ok = self.dialog_runner(dlg) if self.dialog_runner else dlg.exec() == QDialog.Accepted
            if not ok:
                return False
            definition_id = dlg.values()["definition"]
        try:
            runtime.start_instance(company_id(), definition_id, self.entity_type, int(self.entity_id), started_by=user_id(),
                                   correlation_key=f"manual:{self.entity_type}:{self.entity_id}:{definition_id}:"
                                                   f"{len(runtime.list_instances(company_id(), entity_type=self.entity_type, entity_id=int(self.entity_id)))}")
        except ValueError as exc:
            QMessageBox.warning(self, "ارسال برای تایید", str(exc))
            return False
        self.refresh()
        if self.on_started:
            self.on_started()
        return True

    def history(self) -> None:
        if self.instance_id is None:
            return
        dlg = TimelineDialog("تاریخچهٔ گردش کار", self.instance_id, self)
        if self.dialog_runner:
            self.dialog_runner(dlg)
        else:
            dlg.exec()

    def guard(self, target_status: str, current_status: str | None = None, title: str = "گردش کار تایید") -> bool:
        """True یعنی ادامه بده؛ وگرنه دلیل را به کاربر می‌گوید."""
        return guard(self, self.entity_type, self.entity_id, target_status, current_status, title)


def guard(parent, entity_type: str | None, entity_id: int | None, target_status: str, current_status: str | None = None,
          title: str = "گردش کار تایید") -> bool:
    """همان بررسی برای فرم‌هایی که نوار ندارند."""
    cid = company_id()
    if not cid or not entity_type or not entity_id:
        return True
    try:
        message = model_events.check(cid, entity_type, int(entity_id), target_status, current_status)
    except Exception:  # noqa: BLE001
        message = None
    if message:
        QMessageBox.warning(parent, title, message)
        return False
    return True
