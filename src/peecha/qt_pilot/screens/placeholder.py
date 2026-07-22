"""صفحه‌ی موقت برایِ ماژول‌هایی که هنوز به Qt مهاجرت نکرده‌اند."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        self._label = QLabel("")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("font-size: 16px; color: #6B6B85;")
        layout.addWidget(self._label)

    def set_module_name(self, module_name: str) -> None:
        self._label.setText(f"ماژول «{module_name}» به‌زودی به Qt6 مهاجرت می‌کند.")
