"""R376: دستیار پرسش از داده — پرسش فارسی، پاسخ با جدول و منبع، باز کردن همان طرح در گزارش‌ساز؛ فقط‌خواندنی."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSplitter, QTableWidgetItem, QVBoxLayout, QWidget,
)

from peecha.services.report_builder import assistant
from peecha.services.report_builder.datasets import NUMERIC
from peecha.ui import theme
from peecha.ui.screens.fixed_assets import company_id, table, user_id
from peecha.ui.screens.report_builder import show_value
from peecha.ui.widgets import FieldGrid, FieldSpec, build_page_header


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


class AssistantScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.main_window = main_window
        self.answer: assistant.Answer | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "دستیار پرسش از داده", "پرسش خود را به فارسی بنویسید (مثلاً «فروش این ماه به تفکیک مشتری»). پاسخ فقط از داده‌هایی است که "
            "اجازهٔ دیدنشان را دارید و منبع هر پاسخ نمایش داده می‌شود. دستیار چیزی ثبت یا تغییر نمی‌دهد؛ برای هر کار مالی فقط فرم "
            "مربوط را پیشنهاد می‌کند تا خودتان بررسی و ثبت کنید."))
        row = QHBoxLayout()
        self.question_field = QLineEdit()
        self.question_field.setPlaceholderText("پرسش خود را بنویسید")
        self.question_field.returnPressed.connect(self.ask)
        self.example_combo = QComboBox()
        self.example_combo.addItem("— نمونهٔ پرسش —", None)
        for text in assistant.EXAMPLES:
            self.example_combo.addItem(text, text)
        self.example_combo.currentIndexChanged.connect(self._example)
        self.ai_box = QCheckBox("کمک هوش مصنوعی برای فهم پرسش")
        self.ai_box.setToolTip("فقط متن پرسش و نام ستون‌ها فرستاده می‌شود، نه داده‌ها.")
        row.addWidget(FieldGrid([FieldSpec("as_q", "پرسش", self.question_field, span=3), FieldSpec("as_ex", "نمونه", self.example_combo, span=1),
                                 FieldSpec("as_ai", "هوش مصنوعی", self.ai_box, span=1)]), 1)
        ask_button = _btn("پرسیدن", "▶️", "primary")
        ask_button.clicked.connect(self.ask)
        row.addWidget(ask_button)
        layout.addLayout(row)
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        self.answer_label = QLabel("")
        self.answer_label.setWordWrap(True)
        lv.addWidget(self.answer_label)
        self.source_label = QLabel("")
        self.source_label.setWordWrap(True)
        lv.addWidget(self.source_label)
        bar = QHBoxLayout()
        self.open_builder_button = _btn("باز کردن همین پرسش در گزارش‌ساز", "🧱")
        self.open_builder_button.clicked.connect(self.open_in_builder)
        self.open_form_button = _btn("باز کردن فرم پیشنهادی (ثبت با خود شما)", "📂")
        self.open_form_button.clicked.connect(self.open_form)
        for b in (self.open_builder_button, self.open_form_button):
            b.setEnabled(False)
            bar.addWidget(b)
        bar.addStretch(1)
        lv.addLayout(bar)
        self.result_table = table([])
        lv.addWidget(self.result_table, 1)
        splitter.addWidget(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel("پرسش‌های قبلی من"))
        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(lambda item: (self.question_field.setText(item.text()), self.ask()))
        rv.addWidget(self.history_list, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 4)
        layout.addWidget(splitter, 1)

    def refresh(self) -> None:
        cid, uid = company_id(), user_id()
        if cid is None or uid is None:
            return
        available = assistant.ai_available(cid)
        self.ai_box.setEnabled(available)
        if not available:
            self.ai_box.setChecked(False)
            self.ai_box.setToolTip("کلید هوش مصنوعی در تنظیمات تولید محتوا وارد نشده است.")
        self.history_list.clear()
        for _when, question in assistant.history(cid, uid):
            self.history_list.addItem(question)

    def _example(self) -> None:
        text = self.example_combo.currentData()
        if text:
            self.question_field.setText(text)

    def ask(self) -> bool:
        cid, uid = company_id(), user_id()
        if cid is None or uid is None:
            return False
        try:
            a = self.answer = assistant.ask(cid, uid, self.question_field.text(), use_ai=self.ai_box.isChecked())
        except ValueError as exc:
            theme.set_status_label(self.answer_label, str(exc), ok=False)
            return False
        theme.set_status_label(self.answer_label, a.text, ok=a.understood)
        self.source_label.setText(self._sources_text(a))
        self.result_table.clear()
        self.result_table.setColumnCount(len(a.headers))
        self.result_table.setHorizontalHeaderLabels(a.headers)
        rows = a.rows + ([a.totals] if a.totals else [])
        self.result_table.setRowCount(len(rows))
        for i, line in enumerate(rows):
            for j, value in enumerate(line):
                text = show_value(value, a.kinds[j] if j < len(a.kinds) else "TEXT")
                if i == len(a.rows) and j == 0 and not text:
                    text = "جمع"
                item = QTableWidgetItem(text)
                if j < len(a.kinds) and a.kinds[j] in NUMERIC:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.result_table.setItem(i, j, item)
        self.open_builder_button.setEnabled(any(s.definition for s in a.sources))
        self.open_form_button.setEnabled(a.action is not None)
        self.refresh()
        return True

    @staticmethod
    def _sources_text(a: assistant.Answer) -> str:
        parts = []
        for s in a.sources:
            parts.append(" | ".join([s.label] + [f"{k}: {v}" for k, v in s.details]))
        if a.used_ai:
            parts.append("پرسش با کمک هوش مصنوعی به طرح گزارش تبدیل شد.")
        return ("منبع: " + " — ".join(parts)) if parts else ""

    def open_in_builder(self) -> bool:
        source = next((s for s in (self.answer.sources if self.answer else []) if s.definition), None)
        if source is None or self.main_window is None:
            return False
        self.main_window.open_screen("REPORTS_BUILDER", then=lambda screen: screen.load_definition(source.definition, self.answer.question))
        return True

    def open_form(self) -> bool:
        if self.answer is None or self.answer.action is None or self.main_window is None:
            return False
        self.main_window.open_screen(self.answer.action.nav_code)
        return True

