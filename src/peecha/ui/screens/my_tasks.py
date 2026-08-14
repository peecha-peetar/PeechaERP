"""کارتابلِ من — صفِ تاییدِ سراسری، مستقل از ماژول. طبقِ درخواستِ صریح
(«سیستمِ کارتابلِ قابلِ‌گسترش برایِ همه‌یِ ماژول‌ها») این صفحه هیچ منطقِ
خاصِ‌ماژولی ندارد؛ فقط services/cartable.py را صدا می‌زند که رویِ
handlerهایِ ثبت‌شده (فعلاً فقط سندِ حسابداری، در journal_entries.py)
کار می‌کند. افزودنِ کارتابل به یک ماژولِ تازه یعنی همان‌جا یک
register_handler + یک ورودی در _OPEN_HANDLERS این‌جا، نه صفحه‌ی تازه."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import cartable as cartable_service
from peecha.ui.widgets import FieldHelpMixin

_REQUEST_TYPE_LABELS = {"CREATE": "ثبت/تایید", "EDIT": "ویرایش", "DELETE": "حذف"}

# طبقِ همان الگویِ registerِ سرویس — هر ماژولی که کارتابل برایش فعال
# می‌شود، فقط یک ورودی این‌جا اضافه می‌کند (form_code -> بازکردنِ سندِ
# مبدا در main_window، با همان الگویِ open_screen موجود).
_OPEN_HANDLERS: dict[str, callable] = {}


def register_open_handler(form_code: str, opener) -> None:
    """opener(main_window, source_record_id) -> None"""
    _OPEN_HANDLERS[form_code] = opener


class _CommentDialog(QDialog):
    def __init__(self, parent, title: str, prompt: str, *, required: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._required = required
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(prompt))
        self.text_edit = QTextEdit()
        self.text_edit.setFixedHeight(90)
        layout.addWidget(self.text_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("تایید")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if self._required and not self.text_edit.toPlainText().strip():
            QMessageBox.warning(self, "خطا", "نوشتنِ دلیل الزامی است.")
            return
        self.accept()

    def comment(self) -> str:
        return self.text_edit.toPlainText().strip()


_COLUMNS = ["ماژول/فرم", "شرح", "نوعِ درخواست", "مرحله", "صادرکننده", "تاریخِ ارسال"]


class MyTasksScreen(FieldHelpMixin, QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._tasks: list[cartable_service.CartableTaskRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("کارتابلِ من")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "همه‌ی اسناد/درخواست‌هایِ در انتظارِ تاییدِ شما، از همه‌یِ ماژول‌هایِ برنامه، این‌جا با هم دیده می‌شوند."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table, stretch=1)

        buttons = QHBoxLayout()
        approve_button = QPushButton("✅")
        approve_button.setObjectName("primaryIconButton")
        approve_button.setFixedWidth(48)
        approve_button.setToolTip("تایید")
        approve_button.clicked.connect(self._approve_selected)
        buttons.addWidget(approve_button)

        reject_button = QPushButton("رد")
        reject_button.setObjectName("dangerButton")
        reject_button.clicked.connect(self._reject_selected)
        buttons.addWidget(reject_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.set_field_help([
            (self.table, "برایِ بازکردنِ خودِ سند، رویِ ردیفش دابل‌کلیک کنید."),
        ])

    def _selected_task(self) -> cartable_service.CartableTaskRow | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        cartable_item_id = selected[0].data(Qt.UserRole)
        return next((t for t in self._tasks if t.cartable_item_id == cartable_item_id), None)

    def refresh(self) -> None:
        if session.current_user is None or session.current_company is None:
            self._tasks = []
        else:
            self._tasks = cartable_service.list_my_tasks(session.current_user.user_id, session.current_company.company_id)

        self.table.setRowCount(len(self._tasks))
        for row_index, task in enumerate(self._tasks):
            values = [
                task.form_label,
                task.description,
                _REQUEST_TYPE_LABELS.get(task.request_type_code, task.request_type_code),
                f"{numerals.to_persian_digits(str(task.current_step_no))} از {numerals.to_persian_digits(str(task.total_steps))}",
                task.submitted_by_name,
                numerals.format_jalali_datetime(task.submitted_at),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, task.cartable_item_id)
                self.table.setItem(row_index, col_index, item)

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        task = next((t for t in self._tasks if t.cartable_item_id == self.table.item(row, 0).data(Qt.UserRole)), None)
        if task is None:
            return
        opener = _OPEN_HANDLERS.get(task.form_code)
        if opener is not None:
            opener(self._main_window, task.source_record_id)

    def _approve_selected(self) -> None:
        task = self._selected_task()
        if task is None or session.current_user is None:
            return
        dialog = _CommentDialog(self, "تاییدِ کارتابل", "توضیحِ اختیاری برایِ تایید:", required=False)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            cartable_service.approve_item(task.cartable_item_id, session.current_user.user_id, dialog.comment())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _reject_selected(self) -> None:
        task = self._selected_task()
        if task is None or session.current_user is None:
            return
        dialog = _CommentDialog(self, "ردِ کارتابل", "دلیلِ رد را بنویسید:", required=True)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            cartable_service.reject_item(task.cartable_item_id, session.current_user.user_id, dialog.comment())
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()
