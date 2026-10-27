"""R343: دکمهٔ «اسناد مرتبط» برای فرم‌های ERP؛ پنجرهٔ اسناد فقط با کلیک بارگذاری می‌شود."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QPushButton


def related_documents_button(parent, entity_type: str, get_id) -> QPushButton:
    """get_id: () -> شناسهٔ رکورد جاری یا None وقتی رکورد هنوز ذخیره نشده است."""
    button = QPushButton("🗂️")
    button.setObjectName("iconButton")
    button.setFixedWidth(44)
    button.setToolTip("اسناد مرتبط (پیوست فایل و عکس‌برداری با موبایل)")
    button.setAccessibleName("اسناد مرتبط")
    button.setCursor(Qt.PointingHandCursor)

    def open_related() -> None:
        record_id = get_id()
        if not record_id:
            QMessageBox.information(parent, "اسناد مرتبط", "اول این رکورد را ذخیره یا از فهرست باز کنید، بعد اسنادش را ببینید.")
            return
        from peecha.ui.screens.dms import RelatedDocumentsDialog

        RelatedDocumentsDialog(parent, entity_type, record_id).exec()

    button.clicked.connect(open_related)
    return button
