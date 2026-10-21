"""نوار گردش کار داخل فرم اسناد (R295): مسیر تایید، «ارسال برای تایید» و تاریخچه.

فقط وقتی دیده می‌شود که برای این نوع سند فرایندی فعال باشد یا سند در گردش کار باشد؛ در غیر این صورت فرم دقیقاً مثل
قبل است. guard() پیش از عملیات چندمرحله‌ای (مثل ثبت نهایی) قفل تایید را بررسی می‌کند تا هیچ کاری نیمه‌کاره نماند.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget

from peecha import numerals
from peecha.services.workflow import definitions, exceptions, model_events, registry, runtime, tasks
from peecha.services.workflow.common import WorkflowError
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.fixed_assets import FormDialog, combo, company_id, fill, table, user_id

ms.ICONS.update({"ارسال برای تایید": ("📨", "primary"), "تاریخچهٔ گردش کار": ("🕘", ""),
                 "انجام مرحلهٔ جاری": ("📋", "primary"), "یادداشت روی مرحله": ("💬", ""),
                 "ارجاع به فرد مناسب": ("↗️", "primary"), "اجرای دوباره": ("🔁", "primary")})

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
        # R323: مرحلهٔ جاری با فرم کامل خودش و یادداشت، از داخل همین سند
        self.step_button = QPushButton("انجام مرحلهٔ جاری")
        self.step_button.clicked.connect(lambda _c=False: self.open_step())
        self.note_button = QPushButton("یادداشت روی مرحله")
        self.note_button.clicked.connect(lambda _c=False: self.add_note())
        # R325: مرحلهٔ بی‌گیرنده (مثلاً تنها تاییدکننده خود درخواست‌کننده است) — بدون این، سند بی‌صدا گیر می‌کرد
        self.reassign_button = QPushButton("ارجاع به فرد مناسب")
        self.reassign_button.clicked.connect(lambda _c=False: self.reassign())
        # R327: اقدام خودکار شکست‌خورده (مثلاً تصویب خود سند پس از تایید) از داخل همین سند دوباره اجرا می‌شود
        self.retry_button = QPushButton("اجرای دوباره")
        self.retry_button.clicked.connect(lambda _c=False: self.retry_failed())
        self.warning = QLabel("")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #EF4444;")
        self.warning.setVisible(False)
        self.unassigned_ids: list[int] = []
        self.main_window = None
        self.open_task_ids: list[int] = []
        self.my_task_ids: list[int] = []
        self.running = False
        self.waiting_names: list[str] = []
        self.retry_exception_id: int | None = None
        self.can_retry = False
        self.gated_resend = False  # سند (مثلاً درخواست ارسال‌شده) می‌تواند دوباره به فرایند «با دروازه» فرستاده شود
        self.gated_ids: list[int] = []
        for b in (self.send_button, self.step_button, self.note_button, self.reassign_button, self.retry_button,
                  self.history_button):
            ms.style_button(b)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(ms.header_card(self.title, self.path, self.send_button, self.step_button, self.note_button,
                                        self.reassign_button, self.retry_button, self.history_button))
        column.addWidget(self.warning)
        outer.addLayout(column)
        self.setVisible(False)

    # --- وضعیت ---------------------------------------------------------------------------------------------
    def set_entity(self, entity_type: str | None, entity_id: int | None) -> None:
        self.entity_type, self.entity_id = entity_type or self.entity_type, entity_id
        self.refresh()

    def _manual(self):
        cid = company_id()
        if not cid or not self.entity_type or registry.get_adapter(self.entity_type) is None:
            return []
        rows = definitions.manual_definitions(cid, self.entity_type)
        self.gated_ids = model_events.unsent_gate(cid, self.entity_type, int(self.entity_id)) \
            if self.gated_resend and self.entity_id else []
        if self.gated_ids:
            have = {d.definition_id for d in rows}
            rows += [d for d in definitions.list_definitions(cid, include_archived=False, entity_type=self.entity_type)
                     if d.definition_id in self.gated_ids and d.definition_id not in have]
        return rows

    def refresh(self) -> None:
        cid = company_id()
        if not cid or not self.entity_type or not self.entity_id:
            self.instance_id = None
            self.running, self.open_task_ids, self.my_task_ids, self.waiting_names = False, [], [], []
            self.retry_exception_id, self.can_retry, self.gated_ids = None, False, []
            self.setVisible(False)
            return
        try:
            rows = runtime.list_instances(cid, entity_type=self.entity_type, entity_id=int(self.entity_id), limit=1)
            manual = self._manual()
        except Exception:  # noqa: BLE001 -- نوار کمکی نباید بارگذاری فرم را متوقف کند
            self.setVisible(False)
            return
        self.instance_id = rows[0].instance_id if rows else None
        running = self.running = bool(rows) and rows[0].status_code in ("RUNNING", "WAITING")
        try:
            self.waiting_names = tasks.waiting_on(cid, self.instance_id) if running else []
        except Exception:  # noqa: BLE001
            self.waiting_names = []
        if rows:
            waiting = (f" <span style='color:#64748B'>(منتظر تصمیم: {'، '.join(self.waiting_names)})</span>"
                       if self.waiting_names else "")
            self.path.setText(path_html(runtime.status_path(cid, rows[0].instance_id)) + waiting)
            self.path.setToolTip(f"{rows[0].definition_name} — {rows[0].status_label}")
        else:
            self.path.setText("<span style='color:#94A3B8'>هنوز برای تایید فرستاده نشده است.</span>")
            self.path.setToolTip("")
        self.send_button.setEnabled(bool(manual) and not running)
        self.history_button.setEnabled(self.instance_id is not None)
        try:
            self.open_task_ids = [t.task_id for t in tasks.list_tasks(cid, status="OPEN", instance_id=self.instance_id)] \
                if running else []
            mine = {t.task_id for t in tasks.list_my_tasks(cid, user_id())} if self.open_task_ids and user_id() else set()
        except Exception:  # noqa: BLE001
            self.open_task_ids, mine = [], set()
        self.my_task_ids = [t for t in self.open_task_ids if t in mine]
        try:
            self.unassigned_ids = [t.task_id for t in tasks.list_unassigned(cid, entity_type=self.entity_type,
                                                                            entity_id=int(self.entity_id))] if running else []
            can_fix = tasks.can_reassign(cid, user_id())
            stuck_message = model_events.busy(cid, self.entity_type, int(self.entity_id)) if self.unassigned_ids else None
        except Exception:  # noqa: BLE001
            self.unassigned_ids, can_fix, stuck_message = [], False, None
        self.reassign_button.setVisible(bool(self.unassigned_ids) and can_fix)
        try:
            failure = model_events.failed(cid, self.entity_type, int(self.entity_id)) if running else None
            owner = next((e.owner_user_id for e in exceptions.list_exceptions(cid, instance_id=self.instance_id)
                          if failure and e.exception_id == failure[0]), None)
        except Exception:  # noqa: BLE001
            failure, owner = None, None
        self.retry_exception_id = failure[0] if failure else None
        self.can_retry = bool(failure) and (can_fix or (owner is not None and owner == user_id()))
        self.retry_button.setVisible(self.can_retry)
        stuck_message = stuck_message or (failure[1] if failure else None)
        self.warning.setText(stuck_message or "")
        self.warning.setVisible(bool(stuck_message))
        self.step_button.setEnabled(bool(self.open_task_ids))
        self.step_button.setToolTip("انجام مرحلهٔ جاری -- " + ("این مرحله منتظر شماست" if self.my_task_ids else
                                                                "دیدن فرم مرحله؛ تصمیم با مسئول همان مرحله است"))
        self.note_button.setEnabled(bool(self.open_task_ids))
        self.setVisible(bool(rows) or bool(manual))

    # --- کارها -----------------------------------------------------------------------------------------------
    def start_if_pending(self) -> bool:
        """R326: «ارسال برای تصویب» خود سند، فرایند تایید دستی را هم شروع می‌کند (کاربر دو دکمه را جدا نمی‌زند)؛
        اگر فرایندی در جریان است یا تعریف‌نشده، کاری نمی‌کند."""
        self.refresh()
        if self.instance_id is not None and not self.send_button.isEnabled():
            return False
        return self.send() if self.send_button.isEnabled() else False

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

    def open_step(self) -> bool:
        """فرم کامل مرحلهٔ جاری؛ اگر مرحله منتظر همین کاربر باشد تصمیم هم از همین‌جا ثبت می‌شود."""
        task_id = (self.my_task_ids or self.open_task_ids or [None])[0]
        if task_id is None:
            return False
        from peecha.ui.screens.workflow_task_form import TaskFormDialog

        dlg = TaskFormDialog(task_id, self, self.main_window)
        ok = self.dialog_runner(dlg) if self.dialog_runner else dlg.exec() == QDialog.Accepted
        self.refresh()
        if dlg.decided and self.on_started:
            self.on_started()
        return bool(ok and dlg.decided)

    def retry_failed(self) -> bool:
        """True یعنی اقدام این بار انجام شد و فرایند جلو رفت."""
        if not self.retry_exception_id:
            return False
        try:
            exceptions.retry(company_id(), self.retry_exception_id, user_id(), "اجرای دوباره از داخل سند")
        except WorkflowError as exc:
            QMessageBox.warning(self, "اجرای دوباره", str(exc))
            return False
        self.refresh()
        if self.on_started:
            self.on_started()
        if self.retry_exception_id:
            QMessageBox.warning(self, "اجرای دوباره", self.warning.text() or "اقدام باز هم انجام نشد.")
            return False
        return True

    def reassign(self, to_user_id: int | None = None) -> bool:
        if not self.unassigned_ids:
            return False
        if to_user_id is None:
            from peecha.ui.screens.workflow_center import company_user_choices

            dlg = FormDialog("ارجاع به فرد مناسب", [("to", "انجام‌دهنده", combo(company_user_choices()))],
                             self.warning.text() or "فردی را که باید این مرحله را انجام دهد انتخاب کنید.", self)
            ok = self.dialog_runner(dlg) if self.dialog_runner else dlg.exec() == QDialog.Accepted
            if not ok:
                return False
            to_user_id = dlg.values().get("to")
        try:
            tasks.reassign_task(company_id(), self.unassigned_ids[0], user_id(), [to_user_id])
        except WorkflowError as exc:
            QMessageBox.warning(self, "ارجاع به فرد مناسب", str(exc))
            return False
        self.refresh()
        return True

    def add_note(self, text: str | None = None) -> bool:
        task_id = (self.my_task_ids or self.open_task_ids or [None])[0]
        if task_id is None:
            return False
        if text is None:
            box = QTextEdit()
            box.setMaximumHeight(90)
            dlg = FormDialog("یادداشت روی مرحله", [("text", "یادداشت", box)],
                             "یادداشت برای افراد همین مرحله و درخواست‌کننده فرستاده می‌شود و در تاریخچه می‌ماند.", self)
            ok = self.dialog_runner(dlg) if self.dialog_runner else dlg.exec() == QDialog.Accepted
            if not ok:
                return False
            text = dlg.values().get("text") or ""
        try:
            tasks.add_comment(company_id(), task_id, user_id(), text)
        except WorkflowError as exc:
            QMessageBox.warning(self, "یادداشت روی مرحله", str(exc))
            return False
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
