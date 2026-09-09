"""مرکزِ رسانه -- طبقِ ادامه‌یِ اولویتِ بخشِ محتوا/بازاریابی: کتابخانه‌یِ
مشترکِ عکس/فایلِ شرکت برایِ استفاده‌یِ دوباره در مقالات/پست‌ها. طبقِ
همان الگویِ زوم/بندانگشتیِ گالریِ عکسِ حسابِ تفصیلی."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import media_center as media_service
from peecha.services import smart_publish as smart_publish_service
from peecha.services.detail_dimensions import is_image_extension
from peecha.ui.widgets import LayoutEditMixin


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (نامِ متدِ Qt)
        self.clicked.emit()
        super().mousePressEvent(event)


class _MediaZoomDialog(QDialog):
    def __init__(self, pixmap: QPixmap, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        screen = QApplication.primaryScreen()
        if screen is not None and not pixmap.isNull():
            max_size = screen.availableSize() * 0.8
            if pixmap.width() > max_size.width() or pixmap.height() > max_size.height():
                pixmap = pixmap.scaled(max_size.width(), max_size.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(pixmap)
        layout.addWidget(label)


class MediaCenterScreen(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("مرکزِ رسانه")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        upload_row = QHBoxLayout()
        upload_button = QPushButton("➕ آپلودِ عکس/فایل")
        upload_button.setObjectName("primaryIconButton")
        upload_button.clicked.connect(self._upload_media)
        upload_row.addWidget(upload_button)
        upload_row.addStretch(1)
        outer.addLayout(upload_row)

        self.gallery_container = QWidget()
        self.gallery_layout = QVBoxLayout(self.gallery_container)
        self.gallery_layout.setContentsMargins(0, 0, 0, 0)
        self.gallery_layout.setSpacing(6)
        self.gallery_layout.addStretch(1)

        gallery_scroll = QScrollArea()
        gallery_scroll.setWidgetResizable(True)
        gallery_scroll.setFrameShape(QFrame.NoFrame)
        gallery_scroll.setWidget(self.gallery_container)
        outer.addWidget(gallery_scroll, stretch=1)

        self.empty_label = QLabel("هنوز هیچ عکس یا فایلی در مرکزِ رسانه ثبت نشده.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty_label)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def _build_media_row(self, attachment) -> QWidget:
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(4, 4, 4, 4)

        is_image = is_image_extension(attachment.file_extension)
        if is_image:
            thumb = _ClickableLabel()
            thumb.setFixedSize(56, 56)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setStyleSheet("border: 1px solid palette(mid); border-radius: 4px;")
            pixmap = QPixmap(attachment.storage_key)
            if not pixmap.isNull():
                thumb.setPixmap(pixmap.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            thumb.setCursor(Qt.PointingHandCursor)
            thumb.setToolTip("برایِ نمایِ بزرگ کلیک کنید")
            thumb.clicked.connect(lambda a=attachment: self._zoom_media(a))
            row.addWidget(thumb)
        else:
            file_label = QLabel("📄")
            file_label.setFixedSize(56, 56)
            file_label.setAlignment(Qt.AlignCenter)
            file_label.setStyleSheet("border: 1px solid palette(mid); border-radius: 4px; font-size: 22px;")
            row.addWidget(file_label)

        row.addWidget(QLabel(attachment.file_name), stretch=1)

        if not is_image:
            open_button = QPushButton("🔗 بازکردن")
            open_button.clicked.connect(lambda _checked=False, a=attachment: self._open_file(a))
            row.addWidget(open_button)
        else:
            process_button = QPushButton("✨ پردازشِ هوشمند")
            process_button.setToolTip("اعمالِ واترمارک/حکِ متن/WebP طبقِ تنظیماتِ Smart Publish -- یک نسخهٔ تازه می‌سازد")
            process_button.clicked.connect(lambda _checked=False, a=attachment: self._process_smart_publish(a))
            row.addWidget(process_button)

        remove_button = QPushButton("🚫 حذف")
        remove_button.clicked.connect(lambda _checked=False, a=attachment: self._remove_media(a.attachment_id))
        row.addWidget(remove_button)

        return row_widget

    def refresh(self) -> None:
        while self.gallery_layout.count() > 1:
            item = self.gallery_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        company_id = self._company_id()
        media_items = media_service.list_media(company_id) if company_id is not None else []
        self.empty_label.setVisible(not media_items)
        for attachment in media_items:
            self.gallery_layout.insertWidget(self.gallery_layout.count() - 1, self._build_media_row(attachment))

    def _zoom_media(self, attachment) -> None:
        pixmap = QPixmap(attachment.storage_key)
        if pixmap.isNull():
            QMessageBox.warning(self, "خطا", "بارگذاریِ عکس ممکن نشد.")
            return
        dialog = _MediaZoomDialog(pixmap, attachment.file_name, self)
        dialog.exec()

    def _open_file(self, attachment) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(attachment.storage_key))

    def _upload_media(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        path, _filter = QFileDialog.getOpenFileName(self, "انتخابِ عکس/فایل", "", "همه‌ی فایل‌ها (*)")
        if not path:
            return
        try:
            media_service.upload_media(company_id, app_session.current_user.user_id, path)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _process_smart_publish(self, attachment) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            processed_bytes = smart_publish_service.process_image_file(company_id, attachment.storage_key)
        except Exception as exc:  # noqa: BLE001 -- خطاهایِ Pillow/فایل متنوع‌اند
            QMessageBox.warning(self, "خطا", str(exc))
            return
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as tmp_file:
            tmp_file.write(processed_bytes)
            tmp_path = tmp_file.name
        try:
            media_service.upload_media(company_id, app_session.current_user.user_id, tmp_path)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        self.refresh()

    def _remove_media(self, attachment_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            media_service.delete_media(attachment_id, company_id, app_session.current_user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()
