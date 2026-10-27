"""R343: صفحه‌های مدیریت اسناد: فهرست و جست‌وجو، فرم سند (مشخصات، فایل‌ها و نسخه‌ها، پیوندها، تاریخچه، گردش کار)،
پیش‌نمایش عکس/PDF/متن، عکس‌برداری با موبایل (QR و وضعیت زنده)، اسناد مرتبط هر رکورد ERP، داشبورد، دسته‌بندی و
تنظیمات. همهٔ داده و دسترسی از services/dms می‌آید."""

from __future__ import annotations

import datetime
import io

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services.dms import capture as dcap
from peecha.services.dms import common as dc
from peecha.services.dms import documents as dms
from peecha.services.dms import entities
from peecha.ui import theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, fill, set_combo, table, user_id
from peecha.ui.widgets import JalaliDateEdit, KpiCard, build_page_header

PAGE_SIZE = 50


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


def _warn(parent, exc: Exception, title: str = "اسناد") -> None:
    QMessageBox.warning(parent, title, str(exc))


def _size(n: int | None) -> str:
    n = n or 0
    return P(f"{n / 1024 / 1024:.1f} مگابایت" if n >= 1024 * 1024 else f"{max(1, n // 1024)} کیلوبایت")


def _when(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        local = value.astimezone() if value.tzinfo else value
        return f"{numerals.format_jalali_date(local.date())} {P(local.strftime('%H:%M'))}"
    return numerals.format_jalali_date(value)


def pick_files(parent) -> list[tuple[str, bytes]]:
    from peecha.services.dms.storage import ALLOWED_EXTENSIONS

    pattern = " ".join(f"*.{e}" for e in ALLOWED_EXTENSIONS)
    paths, _filter = QFileDialog.getOpenFileNames(parent, "انتخاب فایل", "", f"اسناد ({pattern})")
    files = []
    for path in paths:
        with open(path, "rb") as handle:
            files.append((path, handle.read()))
    return files


def _company_users(cid: int) -> list[tuple[str, int]]:
    from sqlalchemy import select

    from peecha.db.base import new_session
    from peecha.db.models.security import User, UserCompany

    with new_session() as session:
        rows = session.execute(select(User.full_name, User.user_id).join(UserCompany, UserCompany.user_id == User.user_id).where(
            UserCompany.company_id == cid, User.is_active.is_(True)).order_by(User.full_name)).all()
    return [(name, uid) for name, uid in rows]


def _branches(cid: int) -> list[tuple[str, int]]:
    from peecha.services import procurement_masters as masters

    return [(b.name, b.branch_id) for b in masters.list_branches(cid)]


# --- پیش‌نمایش ----------------------------------------------------------------------------------------------
class PreviewDialog(QDialog):
    """عکس با جهت درست و بزرگ‌نمایی، صفحه‌های PDF، متن ساده؛ HTML/SVG هرگز اجرا یا نمایش داده نمی‌شود."""

    def __init__(self, name: str, mime: str, data: bytes, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"پیش‌نمایش — {name}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(900, 700)
        self._name, self._data, self._zoom, self._page = name, data, 1.0, 0
        self._pixmap: QPixmap | None = None
        self._pdf = None
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.zoom_in, self.zoom_out, self.fit = _btn("بزرگ‌نمایی", "➕"), _btn("کوچک‌نمایی", "➖"), _btn("اندازهٔ پنجره", "🔲")
        self.prev_page, self.next_page = _btn("صفحهٔ قبل", "▶️"), _btn("صفحهٔ بعد", "◀️")
        self.page_label = QLabel("")
        save = _btn("دریافت فایل", "⬇️")
        for widget in (self.zoom_in, self.zoom_out, self.fit, self.prev_page, self.page_label, self.next_page):
            bar.addWidget(widget)
        bar.addStretch(1)
        bar.addWidget(save)
        layout.addLayout(bar)
        self.area = QScrollArea()
        self.area.setAlignment(Qt.AlignCenter)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.area.setWidget(self.image)
        self.area.setWidgetResizable(False)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.area, 1)
        layout.addWidget(self.text, 1)
        self.zoom_in.clicked.connect(lambda: self._set_zoom(self._zoom * 1.25))
        self.zoom_out.clicked.connect(lambda: self._set_zoom(self._zoom / 1.25))
        self.fit.clicked.connect(self._fit)
        self.prev_page.clicked.connect(lambda: self._show_page(self._page - 1))
        self.next_page.clicked.connect(lambda: self._show_page(self._page + 1))
        save.clicked.connect(self._save)
        self.kind = "none"
        if mime.startswith("image/"):
            self.kind = "image"
            reader = QImageReader()
            buffer = QBuffer()
            buffer.setData(QByteArray(data))
            buffer.open(QIODevice.ReadOnly)
            reader.setDevice(buffer)
            reader.setAutoTransform(True)
            image = reader.read()
            self._pixmap = QPixmap.fromImage(image) if not image.isNull() else None
        elif mime == "application/pdf":
            self.kind = "pdf"
            try:
                import pypdfium2 as pdfium

                self._pdf = pdfium.PdfDocument(data)
            except Exception:  # noqa: BLE001 - PDF خراب
                self._pdf = None
        elif mime.startswith("text/"):
            self.kind = "text"
            self.text.setPlainText(data.decode("utf-8-sig", "replace")[:500_000])
        self.text.setVisible(self.kind == "text")
        self.area.setVisible(self.kind in ("image", "pdf"))
        for widget in (self.zoom_in, self.zoom_out, self.fit):
            widget.setVisible(self.kind in ("image", "pdf"))
        for widget in (self.prev_page, self.next_page, self.page_label):
            widget.setVisible(self.kind == "pdf")
        if self.kind == "pdf" and self._pdf is not None:
            self._show_page(0)
        elif self.kind == "image" and self._pixmap is not None:
            QTimer.singleShot(0, self._fit)
        else:
            message = {"none": "پیش‌نمایش این نوع فایل ممکن نیست؛ با «دریافت فایل» آن را ذخیره و باز کنید.",
                       "image": "عکس خراب است یا خوانده نمی‌شود.", "pdf": "فایل PDF خراب است یا خوانده نمی‌شود."}.get(self.kind)
            if message:
                self.text.setVisible(True)
                self.area.setVisible(False)
                self.text.setPlainText(message)

    def _show_page(self, index: int) -> None:
        if self._pdf is None or not 0 <= index < len(self._pdf):
            return
        self._page = index
        bitmap = self._pdf[index].render(scale=1.6).to_pil().convert("RGB")
        out = io.BytesIO()
        bitmap.save(out, "PNG")
        self._pixmap = QPixmap.fromImage(QImage.fromData(out.getvalue()))
        self.page_label.setText(P(f"صفحهٔ {index + 1} از {len(self._pdf)}"))
        self._set_zoom(self._zoom)

    def _set_zoom(self, zoom: float) -> None:
        if self._pixmap is None:
            return
        self._zoom = max(0.1, min(8.0, zoom))
        scaled = self._pixmap.scaled(self._pixmap.size() * self._zoom, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image.setPixmap(scaled)
        self.image.resize(scaled.size())

    def _fit(self) -> None:
        if self._pixmap is None or self._pixmap.width() == 0:
            return
        viewport = self.area.viewport().size()
        self._set_zoom(min(viewport.width() / self._pixmap.width(), viewport.height() / self._pixmap.height(), 1.0) or 1.0)

    def _save(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "ذخیرهٔ فایل", self._name)
        if path:
            with open(path, "wb") as handle:
                handle.write(self._data)

    def done(self, result: int) -> None:
        if self._pdf is not None:
            self._pdf.close()
            self._pdf = None
        super().done(result)


def preview_file(parent, file_id: int) -> None:
    try:
        name, mime, data = dms.read_file(company_id(), user_id(), file_id)
    except (LookupError, FileNotFoundError, ValueError) as exc:
        _warn(parent, exc)
        return
    PreviewDialog(name, mime, data, parent).exec()


# --- عکس‌برداری با موبایل --------------------------------------------------------------------------------------
class CaptureDialog(QDialog):
    """درخواست امن می‌سازد، QR و لینک را نشان می‌دهد و هر دو ثانیه وضعیت را از دیتابیس می‌خواند؛ با تکمیل،
    سیگنال completed با شناسهٔ سند می‌دهد. بستن پنجره زمان‌سنج را متوقف و درخواست بازنشده را لغو می‌کند."""

    completed = Signal(int)
    POLL_MS = 2000

    def __init__(self, parent=None, *, entity_type: str | None = None, entity_id: int | None = None,
                 document_id: int | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("عکس‌برداری با موبایل")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(460)
        self._target = {"entity_type": entity_type, "entity_id": entity_id, "document_id": document_id}
        self.view = None
        layout = QVBoxLayout(self)
        self.target_label = QLabel("")
        self.target_label.setObjectName("sectionTitle")
        self.target_label.setWordWrap(True)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignCenter)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("sectionHint")
        self.link = QLineEdit()
        self.link.setReadOnly(True)
        self.link.setLayoutDirection(Qt.LeftToRight)
        self.status_label = QLabel("")
        self.status_label.setObjectName("sectionTitle")
        self.countdown = QLabel("")
        for widget in (self.target_label, self.qr, self.hint, self.link, self.status_label, self.countdown):
            layout.addWidget(widget)
        bar = QHBoxLayout()
        self.cancel_button = _btn("لغو درخواست", "🚫", "danger")
        self.again_button = _btn("درخواست جدید", "🔄", "primary")
        close = _btn("بستن", "✖️")
        for widget in (self.cancel_button, self.again_button):
            bar.addWidget(widget)
        bar.addStretch(1)
        bar.addWidget(close)
        layout.addLayout(bar)
        self.cancel_button.clicked.connect(self._cancel)
        self.again_button.clicked.connect(self.start)
        close.clicked.connect(self.close)
        self.timer = QTimer(self)
        self.timer.setInterval(self.POLL_MS)
        self.timer.timeout.connect(self.poll)
        self.start()

    def start(self) -> None:
        self.timer.stop()
        try:
            self.view = dcap.create_request(company_id(), user_id(), **self._target)
        except (LookupError, PermissionError, ValueError) as exc:
            self.view = None
            self.target_label.setText(str(exc))
            self.status_label.setText("درخواست ساخته نشد")
            self.cancel_button.setEnabled(False)
            return
        url = dcap.mobile_url(company_id(), self.view.token)
        self.target_label.setText(f"{self.view.target_kind}: {P(self.view.target_label)}")
        app_hint = "در اپ موبایل پیچا هم همین درخواست در «اعلان‌ها» و «عکس‌برداری برای اسناد» دیده می‌شود."
        if url:
            import segno

            buffer = io.BytesIO()
            segno.make(url, error="m").save(buffer, kind="png", scale=7, border=3)
            self.qr.setPixmap(QPixmap.fromImage(QImage.fromData(buffer.getvalue())))
            self.link.setText(url)
            self.link.setVisible(True)
            insecure = " نشانی سرور https نیست؛ فقط در شبکهٔ داخلی آزمایشی استفاده کنید." if url.startswith("http://") else ""
            self.hint.setText("این کد را با دوربین گوشی اسکن کنید، با همان حساب کاربری وارد شوید و عکس بگیرید. " + app_hint + insecure)
        else:
            self.qr.clear()
            self.link.setVisible(False)
            self.hint.setText("نشانی سرور موبایل در «تنظیمات اسناد» تعیین نشده و کد QR ساخته نشد. " + app_hint)
        self.view.token = None
        self._render()
        self.timer.start()

    def poll(self) -> None:
        if self.view is None:
            return
        try:
            self.view = dcap.status(company_id(), user_id(), self.view.request_id)
        except LookupError:
            self.timer.stop()
            return
        self._render()

    def _render(self) -> None:
        view = self.view
        terminal = view.status_code in ("COMPLETED", "CANCELLED", "EXPIRED")
        text = view.status_label
        if view.status_code == "FAILED" and view.failure_reason:
            text += f" — {view.failure_reason} (از گوشی دوباره بفرستید)"
        self.status_label.setText(f"وضعیت: {text}")
        remaining = int((view.expires_at - datetime.datetime.now(datetime.timezone.utc)).total_seconds()) if view.expires_at else 0
        self.countdown.setText("" if terminal else P(f"مهلت باقی‌مانده: {max(0, remaining) // 60}:{max(0, remaining) % 60:02d}"))
        self.cancel_button.setEnabled(not terminal)
        self.again_button.setVisible(terminal and view.status_code != "COMPLETED")
        if terminal:
            self.timer.stop()
            self.qr.clear()
            self.link.clear()
        if view.status_code == "COMPLETED" and view.result_document_id:
            self.status_label.setText("وضعیت: تصویر دریافت و به همین رکورد پیوست شد ✅")
            self.completed.emit(view.result_document_id)

    def _cancel(self) -> None:
        if self.view is None:
            return
        try:
            self.view = dcap.cancel(company_id(), user_id(), request_id=self.view.request_id)
        except (dcap.CaptureError, LookupError) as exc:
            _warn(self, exc)
        self._render()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.timer.stop()
        if self.view is not None and self.view.status_code == "PENDING":
            try:
                dcap.cancel(company_id(), user_id(), request_id=self.view.request_id)
            except (dcap.CaptureError, LookupError):
                pass
        super().closeEvent(event)


# --- انتخاب رکورد برای پیوست ------------------------------------------------------------------------------------
class LinkPicker(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("پیوند به رکورد")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        self.type_box = combo([(e.label, code) for code, e in entities.ENTITY_TYPES.items()
                               if entities.can_access(user_id(), company_id(), code)])
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("بخشی از شماره، کد یا نام")
        self.results = QListWidget()
        layout.addWidget(self.type_box)
        layout.addWidget(self.search_box)
        layout.addWidget(self.results, 1)
        bar = QHBoxLayout()
        ok, close = _btn("پیوند", "🔗", "primary"), _btn("انصراف", "✖️")
        bar.addWidget(ok)
        bar.addStretch(1)
        bar.addWidget(close)
        layout.addLayout(bar)
        self.search_box.textChanged.connect(self._search)
        self.type_box.currentIndexChanged.connect(self._search)
        ok.clicked.connect(self.accept)
        close.clicked.connect(self.reject)
        self.results.itemDoubleClicked.connect(lambda _item: self.accept())
        self._search()

    def _search(self) -> None:
        from peecha.db.base import new_session

        self.results.clear()
        entity_type = self.type_box.currentData()
        if not entity_type:
            return
        with new_session() as session:
            rows = entities.search(session, company_id(), entity_type, numerals.to_ascii_digits(self.search_box.text()))
        for entity_id, label in rows:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entity_id)
            self.results.addItem(item)

    def choice(self) -> tuple[str, int] | None:
        item = self.results.currentItem()
        return (self.type_box.currentData(), item.data(Qt.UserRole)) if item is not None else None


# --- فرم سند ----------------------------------------------------------------------------------------------------
class DocumentDialog(QDialog):
    changed = Signal()

    def __init__(self, parent=None, document_id: int | None = None, *, link: tuple[str, int, str] | None = None,
                 files: list[tuple[str, bytes]] | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(940, 680)
        self.document_id, self._link, self._files = document_id, link, list(files or [])
        self.detail = None
        cid = company_id()
        layout = QVBoxLayout(self)
        self.header = QLabel("")
        self.header.setObjectName("pageTitle")
        layout.addWidget(self.header)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        # مشخصات
        info = QWidget()
        form = QFormLayout(info)
        self.title = QLineEdit()
        self.type_box = combo([(label, code) for code, label in dc.DOCUMENT_TYPES.items()])
        self.category_box = combo([(c.path, c.category_id) for c in dms.list_categories(cid)], "— بدون دسته —")
        self.confidential_box = combo([(label, code) for code, label in dc.CONFIDENTIALITY.items()])
        set_combo(self.confidential_box, "INTERNAL")
        self.responsible_box = combo(_company_users(cid), "—")
        self.branch_box = combo(_branches(cid), "—")
        self.issue = JalaliDateEdit(allow_empty=True)
        self.valid_from = JalaliDateEdit(allow_empty=True)
        self.expiry = JalaliDateEdit(allow_empty=True)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("برچسب‌ها را با ویرگول جدا کنید")
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(90)
        for label, widget in (("عنوان", self.title), ("نوع سند", self.type_box), ("دسته‌بندی", self.category_box),
                              ("محرمانگی", self.confidential_box), ("مسئول پیگیری", self.responsible_box), ("شعبه", self.branch_box),
                              ("تاریخ صدور", self.issue), ("اعتبار از", self.valid_from), ("تاریخ انقضا", self.expiry),
                              ("برچسب‌ها", self.tags), ("توضیحات", self.description)):
            form.addRow(label, widget)
        self.new_files = QListWidget()
        self.new_files_label = QLabel("فایل‌های سند جدید")
        add_files = _btn("افزودن فایل", "📎")
        add_files.clicked.connect(self._add_new_files)
        row = QHBoxLayout()
        row.addWidget(self.new_files, 1)
        row.addWidget(add_files, 0, Qt.AlignTop)
        self.new_files_row = QWidget()
        self.new_files_row.setLayout(row)
        form.addRow(self.new_files_label, self.new_files_row)
        self.tabs.addTab(info, "مشخصات")
        # فایل‌ها و نسخه‌ها
        files_tab = QWidget()
        files_layout = QVBoxLayout(files_tab)
        self.versions = QTreeWidget()
        self.versions.setHeaderLabels(["نسخه / فایل", "تاریخ", "کاربر", "علت یا حجم", "منبع"])
        self.versions.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.versions.itemDoubleClicked.connect(lambda item, _c: self._preview(item))
        files_layout.addWidget(self.versions, 1)
        bar = QHBoxLayout()
        self.preview_button, self.download_button = _btn("پیش‌نمایش", "👁️"), _btn("دریافت فایل", "⬇️")
        self.version_button, self.capture_button = _btn("نسخهٔ جدید", "🗂️"), _btn("عکس‌برداری با موبایل", "📷")
        for widget in (self.preview_button, self.download_button, self.version_button, self.capture_button):
            bar.addWidget(widget)
        bar.addStretch(1)
        files_layout.addLayout(bar)
        self.preview_button.clicked.connect(lambda: self._preview(self.versions.currentItem()))
        self.download_button.clicked.connect(self._download)
        self.version_button.clicked.connect(self._new_version)
        self.capture_button.clicked.connect(self._capture)
        self.tabs.addTab(files_tab, "فایل‌ها و نسخه‌ها")
        # پیوندها
        links_tab = QWidget()
        links_layout = QVBoxLayout(links_tab)
        self.links = table(["نوع رکورد", "رکورد", "وضعیت رکورد", "پیوند توسط", "زمان"])
        links_layout.addWidget(self.links, 1)
        bar = QHBoxLayout()
        self.link_button, self.unlink_button = _btn("پیوند به رکورد", "🔗"), _btn("حذف پیوند", "✂️", "danger")
        bar.addWidget(self.link_button)
        bar.addWidget(self.unlink_button)
        bar.addStretch(1)
        links_layout.addLayout(bar)
        self.link_button.clicked.connect(self._add_link)
        self.unlink_button.clicked.connect(self._remove_link)
        self.tabs.addTab(links_tab, "پیوندها")
        # تاریخچه
        self.events = table(["زمان", "رویداد", "کاربر", "از", "به", "توضیح"])
        self.tabs.addTab(self.events, "تاریخچه")
        # پایین فرم
        footer = QHBoxLayout()
        self.save_button = _btn("ذخیره", "✔️", "primary")
        self.save_button.clicked.connect(self._save)
        footer.addWidget(self.save_button)
        self.action_buttons = {}
        for action, glyph, kind in (("submit", "📨", ""), ("start_review", "🔍", ""), ("approve", "✅", "primary"),
                                    ("request_changes", "✍️", ""), ("reject", "⛔", "danger"), ("obsolete", "🗄️", ""),
                                    ("archive", "📦", ""), ("restore", "📤", "")):
            button = _btn(dc.ACTION_LABELS[action], glyph, kind)
            button.clicked.connect(lambda _checked=False, a=action: self._transition(a))
            footer.addWidget(button)
            self.action_buttons[action] = button
        self.delete_button = _btn("حذف سند", "🗑️", "danger")
        self.delete_button.clicked.connect(self._delete)
        footer.addWidget(self.delete_button)
        footer.addStretch(1)
        self.status = QLabel("")
        footer.addWidget(self.status)
        close = _btn("بستن", "✖️")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.load()

    # بارگذاری
    def load(self) -> None:
        new = self.document_id is None
        self.setWindowTitle("سند جدید" if new else "سند")
        self.new_files_label.setVisible(new)
        self.new_files_row.setVisible(new)
        for index in (1, 2, 3):
            self.tabs.setTabEnabled(index, not new)
        if new:
            self.header.setText("سند جدید" + (f" — پیوست به {P(self._link[2])}" if self._link else ""))
            self.title.setText(self._link[2] if self._link else "")
            self._refresh_new_files()
            for button in (*self.action_buttons.values(), self.delete_button):
                button.setVisible(False)
            return
        try:
            d = self.detail = dms.get_document(company_id(), user_id(), self.document_id)
        except LookupError as exc:
            _warn(self, exc)
            self.reject()
            return
        approved = next((v.version_no for v in d.versions if v.is_approved), None)
        current = next((v.version_no for v in d.versions if v.is_current), None)
        self.header.setText(P(f"{d.document_no} — {d.title}   ·   {d.status_label}" +
                              (f"   ·   نسخهٔ جاری {current}" if current else "") +
                              (f" (تاییدشده: نسخهٔ {approved})" if approved and approved != current else "")))
        self.title.setText(d.title)
        set_combo(self.type_box, d.document_type_code)
        set_combo(self.category_box, d.category_id)
        set_combo(self.confidential_box, d.confidentiality_code)
        set_combo(self.responsible_box, d.responsible_user_id)
        set_combo(self.branch_box, d.branch_id)
        self.issue.setDate(d.issue_date)
        self.valid_from.setDate(d.valid_from)
        self.expiry.setDate(d.expiry_date)
        self.tags.setText("، ".join(d.tags))
        self.description.setPlainText(d.description or "")
        self.versions.clear()
        for v in d.versions:
            marks = (" — جاری" if v.is_current else "") + (" — تاییدشده" if v.is_approved else "")
            node = QTreeWidgetItem([P(f"نسخهٔ {v.version_no}{marks}"), _when(v.created_at), v.created_by, v.reason or "",
                                    {"DESKTOP": "دسکتاپ", "MOBILE": "اپ موبایل", "WEB": "وب موبایل", "API": "API"}.get(v.source_code, "")])
            for f in v.files:
                child = QTreeWidgetItem([f.name, "", "", _size(f.size_bytes), f.extension])
                child.setData(0, Qt.UserRole, f.file_id)
                node.addChild(child)
            self.versions.addTopLevelItem(node)
            node.setExpanded(v.is_current)
        fill(self.links, [[l.type_label, l.label, "فعال" if l.record_active else "غیرفعال یا حذف‌شده", l.created_by,
                           _when(l.created_at)] for l in d.links], [l.link_id for l in d.links])
        fill(self.events, [[_when(e.created_at), e.label, e.user, e.from_status or "", e.to_status or "", e.note or ""]
                           for e in d.events])
        editable = d.can_edit
        for widget in (self.title, self.type_box, self.category_box, self.confidential_box, self.responsible_box,
                       self.branch_box, self.issue, self.valid_from, self.expiry, self.tags, self.description):
            widget.setEnabled(editable)
        self.save_button.setEnabled(editable)
        for widget in (self.version_button, self.capture_button, self.link_button, self.unlink_button):
            widget.setEnabled(editable)
        for action, button in self.action_buttons.items():
            if action in dc.TRANSITIONS:
                sources, _to, form, _note = dc.TRANSITIONS[action]
                allowed = d.status_code in sources and (d.can_decide if form == dc.FORM_APPROVE else d.can_edit or
                                                         d.owner_user_id == user_id())
            elif action == "archive":
                allowed = d.can_edit
            else:
                allowed = d.status_code == "ARCHIVED" and dc.can(user_id(), company_id(), dc.FORM_DOCS, "EDIT")
            button.setVisible(bool(allowed))
        self.delete_button.setVisible(d.can_delete)

    def _fields(self) -> dms.DocumentFields:
        tags = [t.strip() for t in self.tags.text().replace("،", ",").split(",") if t.strip()]
        return dms.DocumentFields(
            title=self.title.text(), document_type_code=self.type_box.currentData() or "OTHER",
            category_id=self.category_box.currentData(), confidentiality_code=self.confidential_box.currentData() or "INTERNAL",
            responsible_user_id=self.responsible_box.currentData(), branch_id=self.branch_box.currentData(),
            issue_date=self.issue.date(), valid_from=self.valid_from.date(), expiry_date=self.expiry.date(),
            description=self.description.toPlainText(), tags=tags)

    def _refresh_new_files(self) -> None:
        self.new_files.clear()
        for name, data in self._files:
            self.new_files.addItem(f"{name.replace(chr(92), '/').rsplit('/', 1)[-1]} — {_size(len(data))}")

    def _add_new_files(self) -> None:
        self._files += pick_files(self)
        self._refresh_new_files()

    def _run(self, fn, *args, **kwargs):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return fn(*args, **kwargs), True
        except (LookupError, PermissionError, ValueError, FileNotFoundError, dcap.CaptureError) as exc:
            QApplication.restoreOverrideCursor()
            _warn(self, exc)
            return None, False
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

    def _save(self) -> None:
        if self.document_id is None:
            links = [(self._link[0], self._link[1])] if self._link else []
            new_id, ok = self._run(dms.create_document, company_id(), user_id(), self._fields(), self._files, links)
            if ok:
                self.document_id = new_id
        else:
            _r, ok = self._run(dms.update_document, company_id(), user_id(), self.document_id, self._fields(), self.detail.row_version)
        if ok:
            self.status.setText("ذخیره شد")
            self.changed.emit()
            self.load()

    def _selected_file(self) -> int | None:
        item = self.versions.currentItem()
        if item is None:
            return None
        file_id = item.data(0, Qt.UserRole)
        if file_id is None and item.childCount():
            file_id = item.child(0).data(0, Qt.UserRole)
        return file_id

    def _preview(self, item) -> None:
        file_id = self._selected_file() if item is not None else None
        if file_id:
            preview_file(self, file_id)

    def _download(self) -> None:
        file_id = self._selected_file()
        if not file_id:
            return
        result, ok = self._run(dms.read_file, company_id(), user_id(), file_id)
        if ok:
            name, _mime, data = result
            path, _filter = QFileDialog.getSaveFileName(self, "ذخیرهٔ فایل", name)
            if path:
                with open(path, "wb") as handle:
                    handle.write(data)
                self.load()

    def _new_version(self) -> None:
        files = pick_files(self)
        if not files:
            return
        reason, ok = QInputDialog.getText(self, "نسخهٔ جدید", "علت تغییر:")
        if not ok:
            return
        keep = QMessageBox.question(self, "نسخهٔ جدید", "فایل‌های نسخهٔ جاری هم در نسخهٔ جدید بمانند؟ (خیر یعنی جایگزینی)") == QMessageBox.Yes
        _r, done = self._run(dms.add_version, company_id(), user_id(), self.document_id, files, reason, keep_current_files=keep,
                             expected_current_version_id=self.detail.current_version_id)
        if done:
            self.changed.emit()
            self.load()

    def _capture(self) -> None:
        dialog = CaptureDialog(self, document_id=self.document_id)
        dialog.completed.connect(lambda _doc: (self.changed.emit(), self.load()))
        dialog.exec()

    def _add_link(self) -> None:
        picker = LinkPicker(self)
        if picker.exec() == QDialog.Accepted and picker.choice():
            entity_type, entity_id = picker.choice()
            _r, ok = self._run(dms.link_document, company_id(), user_id(), self.document_id, entity_type, entity_id)
            if ok:
                self.changed.emit()
                self.load()

    def _remove_link(self) -> None:
        items = self.links.selectedItems()
        if not items:
            return
        link_id = self.links.item(items[0].row(), 0).data(Qt.UserRole)
        if QMessageBox.question(self, "حذف پیوند", "پیوند این سند با رکورد برداشته شود؟") != QMessageBox.Yes:
            return
        _r, ok = self._run(dms.unlink_document, company_id(), user_id(), link_id)
        if ok:
            self.changed.emit()
            self.load()

    def _transition(self, action: str) -> None:
        note = None
        if action in dc.TRANSITIONS and dc.TRANSITIONS[action][3] or action in ("approve", "obsolete"):
            note, ok = QInputDialog.getText(self, dc.ACTION_LABELS[action], "توضیح:")
            if not ok:
                return
        _r, ok = self._run(dms.transition, company_id(), user_id(), self.document_id, action, note,
                           expected_version_id=self.detail.current_version_id if action == "approve" else None)
        if ok:
            self.changed.emit()
            self.load()

    def _delete(self) -> None:
        if QMessageBox.question(self, "حذف سند", "این سند حذف شود؟ (فایل‌ها و تاریخچه نگه داشته می‌شوند)") != QMessageBox.Yes:
            return
        _r, ok = self._run(dms.delete_document, company_id(), user_id(), self.document_id)
        if ok:
            self.changed.emit()
            self.accept()


# --- اسناد مرتبط یک رکورد --------------------------------------------------------------------------------------------
class RelatedDocumentsDialog(QDialog):
    """از داخل فرم هر رکورد ERP: اسناد پیوسته، سند جدید از فایل، عکس‌برداری با موبایل، پیش‌نمایش و بازکردن سند."""

    def __init__(self, parent, entity_type: str, entity_id: int, label: str | None = None) -> None:
        super().__init__(parent)
        if label is None:
            from peecha.db.base import new_session

            with new_session() as session:
                found = entities.describe(session, company_id(), entity_type, int(entity_id))
            label = found[0] if found else str(entity_id)
        self.entity_type, self.entity_id, self.label = entity_type, int(entity_id), label
        self.setWindowTitle(f"اسناد مرتبط — {P(label)}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(860, 520)
        layout = QVBoxLayout(self)
        self.title = QLabel(P(f"{entities.get(entity_type).label}: {label}"))
        self.title.setObjectName("sectionTitle")
        layout.addWidget(self.title)
        body = QHBoxLayout()
        self.table = table(["شماره", "عنوان", "نوع", "وضعیت", "نسخه", "فایل"])
        self.table.itemSelectionChanged.connect(self._show_thumbnail)
        self.table.itemDoubleClicked.connect(lambda _item: self._open())
        body.addWidget(self.table, 3)
        self.thumbnail = QLabel("")
        self.thumbnail.setAlignment(Qt.AlignCenter)
        self.thumbnail.setMinimumWidth(240)
        body.addWidget(self.thumbnail, 1)
        layout.addLayout(body, 1)
        bar = QHBoxLayout()
        self.new_button, self.capture_button = _btn("سند جدید", "🆕", "primary"), _btn("عکس‌برداری با موبایل", "📷")
        self.open_button, self.preview_button = _btn("بازکردن سند", "📂"), _btn("پیش‌نمایش", "👁️")
        self.unlink_button = _btn("حذف پیوند", "✂️", "danger")
        for widget in (self.new_button, self.capture_button, self.open_button, self.preview_button, self.unlink_button):
            bar.addWidget(widget)
        bar.addStretch(1)
        self.message = QLabel("")
        bar.addWidget(self.message)
        layout.addLayout(bar)
        self.new_button.clicked.connect(self._new)
        self.capture_button.clicked.connect(self._capture)
        self.open_button.clicked.connect(self._open)
        self.preview_button.clicked.connect(self._preview)
        self.unlink_button.clicked.connect(self._unlink)
        can_add = dc.can(user_id(), company_id(), dc.FORM_DOCS, "CREATE")
        self.new_button.setEnabled(can_add)
        self.capture_button.setEnabled(can_add)
        self.unlink_button.setEnabled(dc.can(user_id(), company_id(), dc.FORM_DOCS, "EDIT"))
        self.rows = []
        self.refresh()

    def refresh(self) -> None:
        try:
            self.rows = dms.documents_for_entity(company_id(), user_id(), self.entity_type, self.entity_id)
        except (LookupError, PermissionError, ValueError) as exc:
            self.rows = []
            self.message.setText(str(exc))
        fill(self.table, [[r.document_no, r.title, r.type_label, r.status_label, r.version_no or "", r.file_count] for r in self.rows],
             [r.document_id for r in self.rows])
        self.thumbnail.clear()

    def _selected(self):
        items = self.table.selectedItems()
        if not items:
            return None
        document_id = self.table.item(items[0].row(), 0).data(Qt.UserRole)
        return next((r for r in self.rows if r.document_id == document_id), None)

    def _show_thumbnail(self) -> None:
        row = self._selected()
        self.thumbnail.clear()
        if row is None or not row.first_file_id:
            return
        try:
            _name, _mime, data = dms.read_file(company_id(), user_id(), row.first_file_id, thumbnail=True)
        except LookupError:
            self.thumbnail.setText("بدون تصویر کوچک")
            return
        self.thumbnail.setPixmap(QPixmap.fromImage(QImage.fromData(data)))

    def _new(self) -> None:
        files = pick_files(self)
        if not files:
            return
        dialog = DocumentDialog(self, link=(self.entity_type, self.entity_id, self.label), files=files)
        dialog.changed.connect(self.refresh)
        dialog.exec()

    def _capture(self) -> None:
        dialog = CaptureDialog(self, entity_type=self.entity_type, entity_id=self.entity_id)
        dialog.completed.connect(lambda _doc: (self.refresh(), self.message.setText("تصویر موبایل دریافت شد ✅")))
        dialog.exec()

    def _open(self) -> None:
        row = self._selected()
        if row is not None:
            dialog = DocumentDialog(self, row.document_id)
            dialog.changed.connect(self.refresh)
            dialog.exec()

    def _preview(self) -> None:
        row = self._selected()
        if row is not None and row.first_file_id:
            preview_file(self, row.first_file_id)

    def _unlink(self) -> None:
        row = self._selected()
        if row is None:
            return
        try:
            detail = dms.get_document(company_id(), user_id(), row.document_id)
            link = next(l for l in detail.links if l.entity_type == self.entity_type and l.entity_id == self.entity_id)
        except (LookupError, StopIteration):
            return
        if QMessageBox.question(self, "حذف پیوند", "پیوند این سند با همین رکورد برداشته شود؟ (خود سند می‌ماند)") != QMessageBox.Yes:
            return
        try:
            dms.unlink_document(company_id(), user_id(), link.link_id)
        except (LookupError, PermissionError) as exc:
            _warn(self, exc)
        self.refresh()


# --- فهرست اسناد --------------------------------------------------------------------------------------------------------
class DmsDocumentsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.page = 1
        self.total = 0
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header("اسناد", "همهٔ اسناد و مدارک شرکت با نسخه، پیوند به رکوردهای برنامه و گردش تایید."))
        filters = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("جست‌وجو در عنوان، شماره، توضیح، نام فایل و متن فایل")
        self.type_box = combo([(label, code) for code, label in dc.DOCUMENT_TYPES.items()], "همهٔ نوع‌ها")
        self.status_box = combo([(label, code) for code, label in dc.STATUSES.items()], "همهٔ وضعیت‌ها")
        self.category_box = QComboBox()
        self.expiry_box = combo([("نزدیک به انقضا", "SOON"), ("منقضی‌شده", "EXPIRED")], "همهٔ تاریخ‌ها")
        self.tag_box = QLineEdit()
        self.tag_box.setPlaceholderText("برچسب")
        self.tag_box.setMaximumWidth(140)
        self.archived = QCheckBox("با بایگانی‌شده‌ها")
        search = _btn("جستجو", "🔍", "primary")
        for widget in (self.search_box, self.type_box, self.status_box, self.category_box, self.expiry_box, self.tag_box, self.archived, search):
            filters.addWidget(widget)
        layout.addLayout(filters)
        self.table = table(["شماره", "عنوان", "نوع", "دسته", "وضعیت", "محرمانگی", "نسخه", "فایل", "انقضا", "مسئول"])
        self.table.itemDoubleClicked.connect(lambda _item: self.open_selected())
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.new_button, self.open_button = _btn("سند جدید", "🆕", "primary"), _btn("بازکردن سند", "📂")
        self.preview_button, self.capture_button = _btn("پیش‌نمایش", "👁️"), _btn("عکس‌برداری با موبایل", "📷")
        for widget in (self.new_button, self.open_button, self.preview_button, self.capture_button):
            bar.addWidget(widget)
        bar.addStretch(1)
        self.prev_button, self.next_button = _btn("صفحهٔ قبل", "▶️"), _btn("صفحهٔ بعد", "◀️")
        self.page_label = QLabel("")
        bar.addWidget(self.prev_button)
        bar.addWidget(self.page_label)
        bar.addWidget(self.next_button)
        layout.addLayout(bar)
        search.clicked.connect(lambda: self.load(1))
        self.search_box.returnPressed.connect(lambda: self.load(1))
        self.new_button.clicked.connect(self.new_document)
        self.open_button.clicked.connect(self.open_selected)
        self.preview_button.clicked.connect(self.preview_selected)
        self.capture_button.clicked.connect(self.capture_selected)
        self.prev_button.clicked.connect(lambda: self.load(self.page - 1))
        self.next_button.clicked.connect(lambda: self.load(self.page + 1))
        self.rows = []

    def refresh(self) -> None:
        if company_id() is None:
            return
        current = self.category_box.currentData()
        self.category_box.clear()
        self.category_box.addItem("همهٔ دسته‌ها", None)
        for category in dms.list_categories(company_id()):
            self.category_box.addItem(P(category.path), category.category_id)
        set_combo(self.category_box, current)
        self.new_button.setEnabled(dc.can(user_id(), company_id(), dc.FORM_DOCS, "CREATE"))
        self.load(self.page)

    def filters(self) -> dms.SearchFilters:
        expiry = self.expiry_box.currentData()
        status = self.status_box.currentData()
        return dms.SearchFilters(
            text=numerals.to_ascii_digits(self.search_box.text()) if self.search_box.text().strip() else None,
            document_type_code=self.type_box.currentData(), category_id=self.category_box.currentData(),
            statuses=[status] if status else None, include_archived=self.archived.isChecked(),
            tag=self.tag_box.text().strip() or None, expired_only=expiry == "EXPIRED",
            expiring_within_days=30 if expiry == "SOON" else None)

    def load(self, page: int = 1) -> None:
        pages = max(1, -(-self.total // PAGE_SIZE)) if self.total else 1
        self.page = max(1, min(page, pages)) if page != 1 else 1
        self.rows, self.total = dms.search(company_id(), user_id(), self.filters(), self.page, PAGE_SIZE)
        pages = max(1, -(-self.total // PAGE_SIZE))
        fill(self.table, [[r.document_no, r.title, r.type_label, r.category_name or "", r.status_label, r.confidentiality_label,
                           r.version_no or "", r.file_count, r.expiry_date, r.responsible_name or ""] for r in self.rows],
             [r.document_id for r in self.rows])
        today = datetime.date.today()
        for index, row in enumerate(self.rows):
            if row.expiry_date and row.expiry_date < today:
                self.table.item(index, 8).setForeground(QColor("#d64545"))
        self.page_label.setText(P(f"صفحهٔ {self.page} از {pages} — {self.total} سند"))
        self.prev_button.setEnabled(self.page > 1)
        self.next_button.setEnabled(self.page < pages)

    def selected(self):
        items = self.table.selectedItems()
        if not items:
            return None
        document_id = self.table.item(items[0].row(), 0).data(Qt.UserRole)
        return next((r for r in self.rows if r.document_id == document_id), None)

    def new_document(self) -> None:
        dialog = DocumentDialog(self)
        dialog.changed.connect(lambda: self.load(1))
        dialog.exec()

    def open_selected(self) -> None:
        row = self.selected()
        if row is not None:
            dialog = DocumentDialog(self, row.document_id)
            dialog.changed.connect(lambda: self.load(self.page))
            dialog.exec()

    def preview_selected(self) -> None:
        row = self.selected()
        if row is not None and row.first_file_id:
            preview_file(self, row.first_file_id)

    def capture_selected(self) -> None:
        row = self.selected()
        if row is None:
            QMessageBox.information(self, "عکس‌برداری با موبایل", "اول سندی را که عکس به آن اضافه می‌شود انتخاب کنید.")
            return
        dialog = CaptureDialog(self, document_id=row.document_id)
        dialog.completed.connect(lambda _doc: self.load(self.page))
        dialog.exec()


# --- داشبورد ------------------------------------------------------------------------------------------------------------
class DmsDashboardScreen(QWidget):
    CARDS = (("total", "کل اسناد", "🗂️"), ("pending", "در انتظار بررسی", "⏳"), ("needs_changes", "نیازمند اصلاح", "✍️"),
             ("expiring", "نزدیک به انقضا", "⏰"), ("expired", "منقضی", "⛔"), ("captures_active", "عکس‌برداری‌های فعال", "📷"),
             ("captures_completed", "عکس‌برداری موفق (۷ روز)", "✅"), ("captures_failed", "ناموفق، منقضی یا لغو (۷ روز)", "⚠️"))

    def __init__(self) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header("داشبورد اسناد", "آمار واقعی اسنادی که اجازهٔ دیدنشان را دارید."))
        grid = QGridLayout()
        self.cards = {}
        for index, (key, title, icon) in enumerate(self.CARDS):
            card = KpiCard(title, icon, theme.ACCENT)
            grid.addWidget(card, index // 4, index % 4)
            self.cards[key] = card
        layout.addLayout(grid)
        lists = QHBoxLayout()
        self.recent = table(["شماره", "عنوان", "وضعیت", "ثبت"])
        self.categories = table(["دسته", "تعداد"])
        lists.addWidget(self.recent, 2)
        lists.addWidget(self.categories, 1)
        layout.addLayout(lists, 1)

    def refresh(self) -> None:
        if company_id() is None:
            return
        data = dms.dashboard(company_id(), user_id())
        for key, card in self.cards.items():
            card.value_label.setText(P(getattr(data, key)))
        fill(self.recent, [[r.document_no, r.title, r.status_label, _when(r.created_at)] for r in data.recent],
             [r.document_id for r in data.recent])
        fill(self.categories, [[name, count] for name, count in data.by_category])


# --- دسته‌بندی و برچسب --------------------------------------------------------------------------------------------------
class DmsCategoriesScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header("دسته‌بندی و برچسب اسناد", "دسته‌ها سلسله‌مراتبی‌اند؛ جست‌وجوی یک دسته زیرشاخه‌هایش را هم می‌آورد."))
        body = QHBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["دسته", "وضعیت"])
        self.tags = QListWidget()
        body.addWidget(self.tree, 2)
        body.addWidget(self.tags, 1)
        layout.addLayout(body, 1)
        bar = QHBoxLayout()
        self.add_button, self.child_button = _btn("دسته‌بندی جدید", "🆕", "primary"), _btn("زیردستهٔ جدید", "➕")
        self.edit_button, self.toggle_button = _btn("ویرایش نام", "✏️"), _btn("فعال یا غیرفعال", "⏯️")
        for widget in (self.add_button, self.child_button, self.edit_button, self.toggle_button):
            bar.addWidget(widget)
        bar.addStretch(1)
        layout.addLayout(bar)
        self.add_button.clicked.connect(lambda: self._save(None, None))
        self.child_button.clicked.connect(lambda: self._save(None, self._current()))
        self.edit_button.clicked.connect(self._rename)
        self.toggle_button.clicked.connect(self._toggle)
        self.items = {}

    def refresh(self) -> None:
        if company_id() is None:
            return
        self.tree.clear()
        rows = dms.list_categories(company_id(), include_inactive=True)
        self.items = {r.category_id: r for r in rows}
        nodes = {}
        for row in sorted(rows, key=lambda r: r.path.count("›")):
            node = QTreeWidgetItem([row.name, "فعال" if row.is_active else "غیرفعال"])
            node.setData(0, Qt.UserRole, row.category_id)
            parent = nodes.get(row.parent_category_id)
            (parent.addChild(node) if parent else self.tree.addTopLevelItem(node))
            nodes[row.category_id] = node
        self.tree.expandAll()
        self.tags.clear()
        self.tags.addItems(dms.list_tags(company_id()))

    def _current(self) -> int | None:
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item is not None else None

    def _save(self, category_id, parent_id, name=None, active=True) -> None:
        if name is None:
            name, ok = QInputDialog.getText(self, "دسته‌بندی", "نام دسته:")
            if not ok:
                return
        try:
            dms.save_category(company_id(), user_id(), category_id, name, parent_id, active)
        except (LookupError, PermissionError, ValueError) as exc:
            _warn(self, exc)
        self.refresh()

    def _rename(self) -> None:
        row = self.items.get(self._current())
        if row is None:
            return
        name, ok = QInputDialog.getText(self, "دسته‌بندی", "نام دسته:", text=row.name)
        if ok:
            self._save(row.category_id, row.parent_category_id, name, row.is_active)

    def _toggle(self) -> None:
        row = self.items.get(self._current())
        if row is not None:
            self._save(row.category_id, row.parent_category_id, row.name, not row.is_active)


# --- تنظیمات -----------------------------------------------------------------------------------------------------------
class DmsSettingsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "تنظیمات اسناد",
            "ذخیره در دیتابیس (پیش‌فرض) برای همهٔ کامپیوترها، سرور موبایل و پشتیبان یکسان است. اگر پوشه انتخاب شود، باید یک "
            "پوشهٔ مشترک شبکه باشد که هم برنامه و هم سرور موبایل به آن دسترسی دارند. نشانی سرور موبایل برای کد QR لازم است و "
            "باید با https باشد تا رمز و عکس‌ها در شبکه رمزگذاری شوند؛ http فقط برای آزمایش در شبکهٔ داخلی است."))
        form = QFormLayout()
        self.mode = combo([("داخل دیتابیس", "DB"), ("پوشهٔ مشترک", "FS")])
        self.root = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://erp.example.ir:8443")
        self.url.setLayoutDirection(Qt.LeftToRight)
        self.max_mb, self.minutes, self.photos, self.reminder = QSpinBox(), QSpinBox(), QSpinBox(), QSpinBox()
        for box, low, high in ((self.max_mb, 1, 200), (self.minutes, 2, 120), (self.photos, 1, 30), (self.reminder, 0, 365)):
            box.setRange(low, high)
        self.keep_gps = QCheckBox("موقعیت مکانی (GPS) عکس‌ها نگه داشته شود")
        self.text_extraction = QCheckBox("استخراج متن PDF و Word برای جست‌وجو (روی همین کامپیوتر)")
        self.image_ocr = QCheckBox("خواندن متن عکس‌ها با Tesseract نصب‌شده روی همین کامپیوتر (اختیاری)")
        for label, widget in (("محل ذخیرهٔ فایل‌ها", self.mode), ("مسیر پوشهٔ مشترک", self.root), ("نشانی سرور موبایل", self.url),
                              ("حداکثر حجم هر فایل (مگابایت)", self.max_mb), ("مهلت درخواست عکس‌برداری (دقیقه)", self.minutes),
                              ("حداکثر عکس در هر درخواست", self.photos), ("یادآوری پیش از انقضا (روز)", self.reminder),
                              ("", self.keep_gps), ("", self.text_extraction), ("", self.image_ocr)):
            form.addRow(label, widget)
        layout.addLayout(form)
        bar = QHBoxLayout()
        self.save_button = _btn("ذخیره", "💾", "primary")
        self.save_button.clicked.connect(self.save)
        bar.addWidget(self.save_button)
        bar.addStretch(1)
        self.status = QLabel("")
        bar.addWidget(self.status)
        layout.addLayout(bar)
        layout.addStretch(1)

    def refresh(self) -> None:
        from peecha.db.base import new_session

        if company_id() is None:
            return
        with new_session() as session:
            cfg = dc.settings(session, company_id())
            session.commit()
            set_combo(self.mode, cfg.storage_mode)
            self.root.setText(cfg.storage_root or "")
            self.url.setText(cfg.mobile_base_url or "")
            self.max_mb.setValue(cfg.max_file_mb)
            self.minutes.setValue(cfg.capture_minutes)
            self.photos.setValue(cfg.capture_max_photos)
            self.reminder.setValue(cfg.expiry_reminder_days)
            self.keep_gps.setChecked(cfg.keep_gps)
            self.text_extraction.setChecked(cfg.text_extraction)
            self.image_ocr.setChecked(cfg.image_ocr)
        self.save_button.setEnabled(dc.can(user_id(), company_id(), dc.FORM_SETTINGS, "EDIT"))

    def save(self) -> None:
        try:
            dc.save_settings(company_id(), user_id(), {
                "storage_mode": self.mode.currentData(), "storage_root": self.root.text(), "mobile_base_url": self.url.text(),
                "max_file_mb": self.max_mb.value(), "capture_minutes": self.minutes.value(),
                "capture_max_photos": self.photos.value(), "expiry_reminder_days": self.reminder.value(),
                "keep_gps": self.keep_gps.isChecked(), "text_extraction": self.text_extraction.isChecked(),
                "image_ocr": self.image_ocr.isChecked()})
        except (PermissionError, ValueError) as exc:
            _warn(self, exc)
            return
        self.status.setText("ذخیره شد")
