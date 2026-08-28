"""طبقِ درخواستِ صریح: ابزارِ فنی/محدود (نه یک ویژگیِ عمومی) برایِ
خام‌کردنِ اطلاعاتِ شرکتِ جاری، به‌تفکیکِ سه دسته‌یِ کاملاً جدا — تا
بشود بدونِ نیاز به بازتعریفِ کدینگ/تنظیمات، بارها اسناد را پاک و
دوباره تست کرد. هر عملیات برگشت‌ناپذیر است؛ پیش از هرکدام، تایپِ کدِ
شرکت الزامی است (نه فقط یک تاییدِ ساده‌یِ بله/خیر)."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QLineEdit, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget

from peecha import session
from peecha.services import data_reset as reset_service
from peecha.ui.widgets import FieldHelpMixin, wrap_scrollable_with_footer


class _ResetSection(QWidget):
    def __init__(self, title: str, description: str, button_label: str, run) -> None:
        super().__init__()
        self._run = run
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)

        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        desc = QLabel(description)
        desc.setObjectName("sectionHint")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.confirm_hint = QLabel()
        self.confirm_hint.setObjectName("sectionHint")
        layout.addWidget(self.confirm_hint)

        self.confirm_field = QLineEdit()
        self.confirm_field.setPlaceholderText("برایِ تاییدِ این عملیاتِ برگشت‌ناپذیر، کدِ شرکت را این‌جا تایپ کنید")
        self.confirm_field.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.confirm_field)

        self.action_button = QPushButton(button_label)
        self.action_button.setObjectName("dangerButton")
        self.action_button.setEnabled(False)
        self.action_button.clicked.connect(self._on_click)
        layout.addWidget(self.action_button)

        self._refresh_hint()

    def _expected_code(self) -> str:
        return session.current_company.code if session.current_company else ""

    def _refresh_hint(self) -> None:
        code = self._expected_code()
        self.confirm_hint.setText(f"کدِ شرکتِ جاری برایِ تایید: «{code}»" if code else "شرکتِ جاری نامشخص است.")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_hint()

    def _on_text_changed(self, text: str) -> None:
        self._refresh_hint()
        expected = self._expected_code()
        # طبقِ گزارشِ کاربر: تایپِ صحیحِ کد ولی با حروفِ کوچک/بزرگِ متفاوت
        # یا فاصله‌یِ اضافه، بدونِ هیچ بازخوردی رد می‌شد -- چون مقایسه
        # قبلاً حساس‌به‌حروف و بدونِ trim بود.
        self.action_button.setEnabled(bool(expected) and text.strip().casefold() == expected.strip().casefold())

    def _on_click(self) -> None:
        confirm = QMessageBox.question(
            self,
            "تاییدِ نهایی",
            "این عملیات برگشت‌ناپذیر است. آیا مطمئنید؟ (پیشنهاد: پیش از این کار، از «پشتیبان‌گیری و بازیابی» یک بک‌آپ بگیرید.)",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self._run()
        self.confirm_field.clear()


class SystemDataResetScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(10)

        title = QLabel("خام‌کردنِ اطلاعات (ابزارِ فنی — فقط برایِ تست/راه‌اندازیِ اولیه)")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "هرکدام از این سه عملیات فقط رویِ شرکتِ جاری اثر می‌گذارد و ساختارِ برنامه/تنظیماتِ سراسری را "
            "دست‌نخورده می‌گذارد. هرسه بازگشت‌ناپذیرند — قبل از اجرا، پیشنهاد می‌شود از «پشتیبان‌گیری و بازیابی» "
            "یک بک‌آپ بگیرید."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.documents_section = _ResetSection(
            "۱) اسناد (فروش/خرید + انبار + مالی/حسابداری)",
            "همه‌یِ سفارش/پیش‌فاکتور/فاکتور/برگشت، سندهایِ انبار (رسید/حواله/اصلاح)، و اسنادِ حسابداری با هم "
            "پاک می‌شوند — چون به هم وصل‌اند. اطلاعاتِ پایه و تنظیمات دست‌نخورده می‌مانند. توجه: تنخواه‌گردان‌ها و "
            "چک‌ها هم چون هرکدام سندِ حسابداریِ خودشان را دارند، جزوِ همین دسته‌اند. ماژول‌هایِ کمترمعمول "
            "(فروشگاه/باشگاهِ مشتریان/گارانتی و RMA/بازارهایِ آنلاین/شمارشِ چرخه‌ای) پوشش داده نمی‌شوند — اگر "
            "چیزی از آن‌ها به این اسناد وابسته باشد، عملیات با پیامِ روشن متوقف می‌شود و هیچ‌چیز حذف نمی‌شود.",
            "پاک‌کردنِ همه‌یِ اسناد",
            self._wipe_documents,
        )
        layout.addWidget(self.documents_section)

        self.master_data_section = _ResetSection(
            "۲) اطلاعاتِ پایه (حساب‌ها، کالاها، انبارها، مشتریان/تامین‌کنندگان، فهرستِ قیمت، بانک‌ها و...)",
            "فقط وقتی مجاز است که هیچ سندی نمانده باشد (ابتدا گزینه‌یِ ۱ را بزنید). نگاشتِ حساب‌ها هم چون به "
            "همین حساب‌ها وصل است، با این عملیات پاک می‌شود.",
            "پاک‌کردنِ اطلاعاتِ پایه",
            self._wipe_master_data,
        )
        layout.addWidget(self.master_data_section)

        self.settings_section = _ResetSection(
            "۳) تنظیمات (نگاشتِ حساب‌ها، سطح‌بندیِ کدینگ، شماره‌گذاریِ اسناد، Toggleهایِ ماژول)",
            "مستقل از دو موردِ بالاست — بدونِ نیاز به پاک‌کردنِ اسناد/اطلاعاتِ پایه هم قابلِ‌اجراست. تعریف‌هایِ "
            "سراسریِ مشترکِ بینِ همه‌یِ شرکت‌ها (مثلاً فهرستِ ویژگی‌هایِ قابلِ‌فعال‌سازی) هرگز پاک نمی‌شوند.",
            "پاک‌کردنِ تنظیمات",
            self._wipe_settings,
        )
        layout.addWidget(self.settings_section)
        layout.addStretch(1)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(100)
        self.status_text.setPlaceholderText("نتیجه‌یِ آخرین عملیات این‌جا نشان داده می‌شود.")
        layout.addWidget(self.status_text)

        outer.addWidget(wrap_scrollable_with_footer(panel, []))

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _run(self, func, success_message: str) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            func(company_id)
        except ValueError as exc:
            self.status_text.setPlainText(str(exc))
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.status_text.setPlainText(success_message)
        QMessageBox.information(self, "انجام شد", success_message)

    def _wipe_documents(self) -> None:
        self._run(reset_service.wipe_documents, "همه‌یِ اسنادِ فروش/خرید، انبار، و مالی/حسابداریِ این شرکت پاک شدند.")

    def _wipe_master_data(self) -> None:
        self._run(reset_service.wipe_master_data, "اطلاعاتِ پایه‌یِ این شرکت پاک شدند.")

    def _wipe_settings(self) -> None:
        self._run(reset_service.wipe_settings, "تنظیماتِ این شرکت پاک شدند.")
