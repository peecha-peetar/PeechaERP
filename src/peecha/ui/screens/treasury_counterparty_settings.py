"""تعریفِ انواعِ سندِ دریافت/پرداخت — طبقِ درخواستِ صریح: در هر ردیف یک
«نوعِ تفصیلی» (مثلاً «مشتری») انتخاب می‌شود و در ستونِ بعدی معینِ حسابِ
مربوطه — سمتِ بستانکار برایِ دریافت، سمتِ بدهکار برایِ پرداخت."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import treasury as treasury_service
from peecha.ui import theme
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo
from peecha.ui.widgets import FieldHelpMixin


class _MultiSelectComboBox(QComboBox):
    """کمبوباکسی که popupِ آن یک چک‌لیستِ چندانتخابیِ شناور است — طبقِ
    گزارشِ صریح («کومبوباکس و چک‌لیست که در لیستِ شناور انتخاب بشه»):
    ظاهرش یک کمبویِ معمولی‌ست (متنِ خلاصه‌یِ گزینه‌هایِ تیک‌خورده را نشان
    می‌دهد)، اما کلیک رویِ هر گزینه، popup را نمی‌بندد تا بشود چند مورد
    را پشتِ‌هم تیک زد — با تکنیکِ استانداردِ override کردنِ hidePopup
    (وگرنه QComboBox با هر کلیکِ رویِ یک آیتم، popup را می‌بندد).

    نکته‌یِ ریشه‌ایِ باگِ گزارش‌شده («کمبو اصلاً باز نمی‌شود»): وقتی
    QComboBox.setEditable(True) باشد، Qt فقط با کلیکِ رویِ فلشِ کوچکِ
    لبه (نه هرجایِ کمبو) popup را باز می‌کند — کلیک رویِ خودِ متن دیگر
    این کار را نمی‌کند (چون آن ناحیه مالِ ویرایشِ متن است، حتی اگر
    read-only باشد). این‌جا با یک eventFilter رویِ خودِ lineEdit، هر
    کلیکِ چپ رویِ هرجایِ کمبو را به‌صراحت باز‌کردنِ popup تبدیل می‌کنیم."""

    selectionChanged = Signal()

    def __init__(self, options: list[tuple[int, str]], parent=None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText("— انتخابِ معین(ها) —")
        self.lineEdit().installEventFilter(self)
        model = QStandardItemModel(self)
        for value, label in options:
            item = QStandardItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setData(Qt.Unchecked, Qt.CheckStateRole)
            item.setData(value, Qt.UserRole)
            model.appendRow(item)
        self.setModel(model)
        self.view().pressed.connect(self._toggle_item)
        # طبقِ گزارشِ صریح («چند تا نمیشه با هم انتخاب کرد»): override
        # کردنِ hidePopup به‌تنهایی گاهی کافی نیست — کانتینرِ داخلیِ Qt
        # (QComboBoxPrivateContainer) خودش هم رویِ رهاکردنِ کلیک (mouse
        # release) رویِ viewport گوش می‌دهد و می‌تواند مستقل popup را ببندد.
        # این‌جا با eventFilterِ اضافه رویِ خودِ viewport، آن رویداد پیش از
        # رسیدن به منطقِ داخلیِ Qt بلعیده می‌شود — کلیک هنوز رویِ «press»
        # (سیگنالِ pressed، در _toggle_item) اثر می‌کند، فقط «release» دیگر
        # نمی‌تواند popup را ببندد.
        self.view().viewport().installEventFilter(self)
        self._skip_hide = False
        self._refresh_text()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 — نامِ متدِ Qt
        if watched is self.lineEdit() and event.type() == QEvent.MouseButtonPress:
            if self.view().isVisible():
                self.hidePopup()
            else:
                self.showPopup()
            return True
        if watched is self.view().viewport() and event.type() == QEvent.MouseButtonRelease:
            return True
        return super().eventFilter(watched, event)

    def _toggle_item(self, index) -> None:
        item = self.model().itemFromIndex(index)
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        # طبقِ اصلاحِ بالا: چون رویدادِ mouse-release رویِ viewport
        # سرکوب می‌شود، دیگر تلاشی برایِ hidePopup از رویِ همین کلیک پیش
        # نمی‌آید — پس دیگر لازم نیست _skip_hide این‌جا ست شود (وگرنه اگر
        # ست بماند، بستنِ واقعیِ بعدیِ popup — مثلاً با کلیکِ رویِ خودِ
        # lineEdit — به‌اشتباه نادیده گرفته می‌شود).
        self._refresh_text()
        self.selectionChanged.emit()

    def hidePopup(self) -> None:  # noqa: N802 — نامِ متدِ Qt
        if self._skip_hide:
            self._skip_hide = False
            return
        super().hidePopup()

    def _refresh_text(self) -> None:
        labels = self.checked_labels()
        if not labels:
            self.lineEdit().setText("")
        elif len(labels) == 1:
            self.lineEdit().setText(labels[0])
        else:
            self.lineEdit().setText(f"{numerals.to_persian_digits(str(len(labels)))} موردِ انتخاب‌شده")

    def checked_labels(self) -> list[str]:
        return [
            self.model().item(i).text()
            for i in range(self.model().rowCount())
            if self.model().item(i).checkState() == Qt.Checked
        ]

    def checked_data(self) -> list:
        return [
            self.model().item(i).data(Qt.UserRole)
            for i in range(self.model().rowCount())
            if self.model().item(i).checkState() == Qt.Checked
        ]

    def set_checked_data(self, values) -> None:
        value_set = set(values)
        for i in range(self.model().rowCount()):
            item = self.model().item(i)
            item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in value_set else Qt.Unchecked)
        self._refresh_text()


class _MappingForm(QWidget):
    """ردیفِ افزودنِ نگاشتِ تازه: یک گروهِ تفصیلی + چند معین با هم — طبقِ
    گزارشِ صریح («بتوان چند معین را به آن تخصیص داد و برای هر گروهِ
    تفصیلی یک بار تعریف بشه»): قبلاً برایِ هر معین باید دوباره همان گروه
    از کمبو انتخاب و «افزودن» زده می‌شد؛ حالا گروه یک‌بار انتخاب می‌شود و
    معین‌ها با همان _MultiSelectComboBoxِ چندانتخابیِ موجود (هم‌الگو با
    _MultiAccountMappingRow) در یک عملیات ثبت می‌شوند."""

    def __init__(self, direction: str, screen: "TreasuryCounterpartySettingsScreen") -> None:
        super().__init__()
        self._direction = direction
        self._screen = screen

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 4)

        self.group_combo = QComboBox()
        self._layout.addWidget(self.group_combo, stretch=1)

        self.account_combo = _MultiSelectComboBox([])
        self._layout.addWidget(self.account_combo, stretch=1)

        add_button = QPushButton("➕")
        add_button.setObjectName("iconButton")
        add_button.setFixedWidth(44)
        add_button.setToolTip("افزودن")
        add_button.clicked.connect(self._add)
        self._layout.addWidget(add_button)

    def set_options(self, group_options: list[tuple[tuple[str, int], str]], account_options: list[tuple[int, str]]) -> None:
        self.group_combo.clear()
        self.group_combo.addItem("— انتخابِ گروهِ تفصیلی —", None)
        for data, label in group_options:
            self.group_combo.addItem(label, data)
        # _MultiSelectComboBox گزینه‌هایش را فقط در سازنده می‌گیرد — برایِ
        # به‌روزرسانیِ گزینه‌ها (هم‌الگو با refreshِ _MultiAccountMappingRow)
        # کمبویِ قبلی با یکِ تازه جایگزین می‌شود.
        old_combo = self.account_combo
        self.account_combo = _MultiSelectComboBox(account_options)
        self._layout.replaceWidget(old_combo, self.account_combo)
        old_combo.deleteLater()

    def _add(self) -> None:
        company_id = self._screen.company_id
        group_data = self.group_combo.currentData()
        account_ids = self.account_combo.checked_data()
        if company_id is None or group_data is None or not account_ids:
            self._screen.set_status("گروهِ تفصیلی و دستِ‌کم یک معین را انتخاب کنید.")
            return
        kind, key = group_data
        try:
            for account_id in account_ids:
                treasury_service.create_counterparty_mapping(
                    company_id,
                    self._direction,
                    account_id,
                    person_group_id=key if kind == "person" else None,
                    dimension_type_id=key if kind == "dim" else None,
                )
        except ValueError as exc:
            self._screen.set_status(str(exc))
            return
        self._screen.set_status("ذخیره شد.", ok=True)
        self.group_combo.setCurrentIndex(0)
        self.account_combo.set_checked_data([])
        self._screen.refresh_mappings(self._direction)


def _describe_account_requirements(account_ids: list[int]) -> str:
    """طبقِ گزارشِ صریح («این چه ربطی به معین داره»): توضیح می‌دهد فهرستِ
    تفصیلیِ این ردیف در فرمِ سند از کجا می‌آید — مستقیماً از رویِ گروه‌هایِ
    شخصیِ الزامی/بُعدهایِ الزامیِ همان معین(ها)، طبقِ تنظیماتِ فعلیِ آن‌ها
    در «کدینگِ حسابداری». اگر فهرستِ تفصیلی اشتباه/بیش‌ازحد‌گسترده است،
    محلِ اصلاح همان‌جاست، نه این صفحه."""
    if not account_ids:
        return "هنوز هیچ معینی انتخاب نشده."
    lines = []
    for account_id in account_ids:
        groups = dimensions_service.get_required_person_groups_for_account(account_id)
        dims = dimensions_service.get_required_dimensions_for_account(account_id)
        labels = [g.name for g in groups] + [
            dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(d.code, d.code) for d in dims
        ]
        lines.append("— " + (" / ".join(labels) if labels else "بدونِ محدودیت (همه‌یِ تفصیلی‌هایِ شرکت)"))
    return (
        "تفصیلی‌هایی که در فرمِ سند برایِ این ردیف پیشنهاد می‌شوند، طبقِ همین محدودیت‌هایِ "
        "معین(ها) (تنظیم‌شده در کدینگِ حسابداری ← ویرایشِ معین) تعیین می‌شوند:\n\n"
        + "\n".join(lines)
        + "\n\nبرایِ محدودکردن/اصلاحِ این فهرست، همان معین را در کدینگِ حسابداری ویرایش کنید."
    )


class _MethodMappingRow(QWidget):
    """ردیفِ نگاشتِ معینِ یک روشِ ردیفِ پایینِ سندِ دریافت (نقد/چک/تخفیف) —
    طبقِ درخواستِ صریح: طرفِ بدهکارِ همین ردیف‌ها، در تنظیماتِ سند. جدا از
    معین، می‌شود یک تفصیلیِ مشخص هم از پیش تخصیص داد — اگر خالی بماند،
    کاربر خودش در فرمِ سند تفصیلی را انتخاب می‌کند."""

    def __init__(
        self,
        mapping_key: str,
        label: str,
        current_account_id: int | None,
        current_detail_account_id: int | None,
        account_options,
        detail_options,
        on_save,
    ) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        name_label = QLabel(label)
        name_label.setMinimumWidth(200)
        layout.addWidget(name_label)

        self.account_combo = _make_searchable_combo(account_options)
        if current_account_id is not None:
            index = self.account_combo.findData(current_account_id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
                self.account_combo.lineEdit().setCursorPosition(0)
        layout.addWidget(self.account_combo, stretch=1)

        self.detail_combo = _make_searchable_combo(detail_options)
        self.detail_combo.setPlaceholderText("تفصیلیِ اختصاصی (اختیاری)")
        if current_detail_account_id is not None:
            index = self.detail_combo.findData(current_detail_account_id)
            if index >= 0:
                self.detail_combo.setCurrentIndex(index)
                self.detail_combo.lineEdit().setCursorPosition(0)
        layout.addWidget(self.detail_combo, stretch=1)

        info_button = QPushButton("؟")
        info_button.setObjectName("flatButton")
        info_button.setToolTip("این ردیف چرا این تفصیلی‌ها را نشان می‌دهد؟")
        info_button.setMaximumWidth(28)
        info_button.clicked.connect(
            lambda: QMessageBox.information(
                self, "منشأِ فهرستِ تفصیلی",
                _describe_account_requirements(
                    [self.account_combo.currentData()] if self.account_combo.currentData() is not None else []
                ),
            )
        )
        layout.addWidget(info_button)

        # طبقِ گزارشِ صریح («وقتی معین را عوض می‌کنیم ذخیره نمی‌شود»): دکمه‌یِ
        # ذخیره تا وقتی چیزی در همین ردیف عوض نشده غیرفعال است — تا هم
        # روشن باشد چه زمانی چیزی برایِ ذخیره‌کردن هست، هم بعدِ ذخیره‌یِ
        # موفق (با پیامِ تاییدیه) دوباره غیرفعال شود تا کلیکِ تکراری معنی
        # نداشته باشد.
        self.save_button = QPushButton("💾")
        self.save_button.setObjectName("iconButton")
        self.save_button.setFixedWidth(44)
        self.save_button.setToolTip("ذخیره")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(lambda: self._on_save_clicked(mapping_key, on_save))
        layout.addWidget(self.save_button)

        self.account_combo.currentIndexChanged.connect(self._mark_dirty)
        self.detail_combo.currentIndexChanged.connect(self._mark_dirty)

    def _mark_dirty(self, _index: int) -> None:
        self.save_button.setEnabled(True)

    def _on_save_clicked(self, mapping_key: str, on_save) -> None:
        saved = on_save(mapping_key, self.account_combo.currentData(), self.detail_combo.currentData())
        if saved:
            QMessageBox.information(self, "ذخیره شد", "تغییراتِ این ردیف ذخیره شد.")
            self.save_button.setEnabled(False)


class _MultiAccountMappingRow(QWidget):
    """طبقِ آیتمِ ۹: ردیفِ نگاشتِ چندمعینیِ یک روشِ دریافت — چک‌لیستِ
    چندانتخابیِ معین‌ها (هم‌الگو با فهرستِ چندانتخابیِ CHECK_DISBURSEMENT).
    تفصیلیِ اختصاصیِ اختیاری فقط وقتی معنی دارد که دقیقاً یک معین تیک
    خورده باشد — وگرنه موقعِ ثبتِ سند، تفصیلی‌هایِ همه‌ی معین‌هایِ
    انتخاب‌شده با هم union می‌شود.

    طبقِ گزارشِ صریح («فضایِ کمتر، مرتب مثلِ قبل» و بعد «کومبوباکس و
    چک‌لیست که در لیستِ شناور انتخاب بشه»): به‌جایِ لیست‌باکسِ همیشه-بازِ
    ۶۴پیکسلی (که مبهم/سخت بود)، همان‌الگویِ ردیفِ تک‌معینیِ قدیمی
    (QHBoxLayoutِ فشرده) با یک _MultiSelectComboBox — ظاهرش دقیقاً یک
    کمبویِ معمولی‌ست، فقط popupِ آن چندانتخابی و شناور است."""

    def __init__(
        self,
        mapping_key: str,
        label: str,
        current_account_ids: list[int],
        current_detail_by_account: dict[int, int],
        account_options,
        detail_options,
        on_save,
    ) -> None:
        super().__init__()
        self._mapping_key = mapping_key
        self._on_save = on_save

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        name_label = QLabel(label)
        name_label.setMinimumWidth(200)
        layout.addWidget(name_label)

        self.account_combo = _MultiSelectComboBox(account_options)
        self.account_combo.set_checked_data(current_account_ids)
        layout.addWidget(self.account_combo, stretch=1)

        self.detail_combo = _make_searchable_combo(detail_options)
        self.detail_combo.setPlaceholderText("تفصیلیِ اختصاصی (اختیاری)")
        if len(current_account_ids) == 1:
            preset_detail = current_detail_by_account.get(current_account_ids[0])
            if preset_detail is not None:
                index = self.detail_combo.findData(preset_detail)
                if index >= 0:
                    self.detail_combo.setCurrentIndex(index)
                    self.detail_combo.lineEdit().setCursorPosition(0)
        layout.addWidget(self.detail_combo, stretch=1)

        info_button = QPushButton("؟")
        info_button.setObjectName("flatButton")
        info_button.setToolTip("این ردیف چرا این تفصیلی‌ها را نشان می‌دهد؟")
        info_button.setMaximumWidth(28)
        info_button.clicked.connect(
            lambda: QMessageBox.information(
                self, "منشأِ فهرستِ تفصیلی", _describe_account_requirements(self.account_combo.checked_data())
            )
        )
        layout.addWidget(info_button)

        # طبقِ گزارشِ صریح: دکمه‌یِ ذخیره فقط وقتی این ردیف تغییر کرده فعال
        # می‌شود، و بعدِ ذخیره‌یِ موفق (با پیامِ تاییدیه) دوباره غیرفعال می‌شود.
        self.save_button = QPushButton("💾")
        self.save_button.setObjectName("iconButton")
        self.save_button.setFixedWidth(44)
        self.save_button.setToolTip("ذخیره")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._on_save_clicked)
        layout.addWidget(self.save_button)

        self.account_combo.selectionChanged.connect(self._mark_dirty)
        self.detail_combo.currentIndexChanged.connect(self._mark_dirty)

    def _mark_dirty(self, *_args) -> None:
        self.save_button.setEnabled(True)

    def _on_save_clicked(self) -> None:
        checked_ids = self.account_combo.checked_data()
        detail_account_id = self.detail_combo.currentData() if len(checked_ids) == 1 else None
        saved = self._on_save(self._mapping_key, checked_ids, detail_account_id)
        if saved:
            QMessageBox.information(self, "ذخیره شد", "تغییراتِ این ردیف ذخیره شد.")
            self.save_button.setEnabled(False)


class _CustomMethodForm(QWidget):
    """طبقِ آیتمِ ۷ (درخواستِ صریح: «بتونیم روش پرداخت و دریافت خودمون
    درست کنیم غیر از موارد پیش‌فرض»): افزودنِ یک روشِ سفارشیِ تازه —
    فقط یک برچسب لازم است؛ کدِ داخلیِ یکتایش خودکار از رویِ همان برچسب
    ساخته می‌شود (کاربر نیازی به واردکردنِ کد ندارد)."""

    def __init__(self, direction: str, screen: "TreasuryCounterpartySettingsScreen") -> None:
        super().__init__()
        self._direction = direction
        self._screen = screen

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        self.label_field = QLineEdit()
        self.label_field.setPlaceholderText("مثلاً «تهاترِ ارزی» یا «کارت‌به‌کارت»")
        layout.addWidget(self.label_field, stretch=1)

        add_button = QPushButton("➕")
        add_button.setObjectName("iconButton")
        add_button.setFixedWidth(44)
        add_button.setToolTip("افزودنِ روشِ سفارشی")
        add_button.clicked.connect(self._add)
        layout.addWidget(add_button)

    def _add(self) -> None:
        label = self.label_field.text().strip()
        if not label:
            self._screen.set_status("برچسبِ روشِ سفارشی را وارد کنید.")
            return
        company_id = self._screen.company_id
        if company_id is None:
            return
        try:
            treasury_service.create_custom_method(company_id, self._direction, label, label)
        except ValueError as exc:
            self._screen.set_status(str(exc))
            return
        self._screen.set_status("ذخیره شد.", ok=True)
        self.label_field.clear()
        self._screen.refresh()


class _CustomMethodRow(QWidget):
    """ردیفِ مدیریتِ یک روشِ سفارشیِ موجود — فعال/غیرفعال و حذف. نگاشتِ
    حسابِ کلِ آن جدا، بلافاصله زیرِ همین ردیف، با یک _MultiAccountMappingRow
    معمولی (عیناً هم‌الگو با روش‌هایِ ثابت) می‌آید."""

    def __init__(self, method: "treasury_service.CustomMethodRow", on_toggle, on_delete) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)

        name_label = QLabel(f"«{method.label}» (سفارشی)")
        name_label.setMinimumWidth(200)
        layout.addWidget(name_label, stretch=1)

        active_checkbox = QCheckBox("فعال")
        active_checkbox.setChecked(method.is_active)
        active_checkbox.toggled.connect(lambda checked: on_toggle(method.custom_method_id, checked))
        layout.addWidget(active_checkbox)

        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(44)
        delete_button.setToolTip("حذفِ روش")
        delete_button.clicked.connect(lambda: on_delete(method.custom_method_id))
        layout.addWidget(delete_button)


class _TemplateRow(QWidget):
    """ردیفِ ویرایشِ قالبِ متنِ خودکارِ شرحِ یک روش — طبقِ درخواستِ صریح
    («دستِ کاربر باشه که چه متنی اعمال بشه»)."""

    def __init__(self, template_key: str, label: str, current_text: str, on_save) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        name_label = QLabel(label)
        name_label.setMinimumWidth(120)
        layout.addWidget(name_label)

        self.text_field = QLineEdit(current_text)
        layout.addWidget(self.text_field, stretch=1)

        self.save_button = QPushButton("💾")
        self.save_button.setObjectName("iconButton")
        self.save_button.setFixedWidth(44)
        self.save_button.setToolTip("ذخیره")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(lambda: self._on_save_clicked(template_key, on_save))
        layout.addWidget(self.save_button)

        self.text_field.textChanged.connect(self._mark_dirty)

    def _mark_dirty(self, _text: str) -> None:
        self.save_button.setEnabled(True)

    def _on_save_clicked(self, template_key: str, on_save) -> None:
        saved = on_save(template_key, self.text_field.text())
        if saved:
            QMessageBox.information(self, "ذخیره شد", "تغییراتِ این ردیف ذخیره شد.")
            self.save_button.setEnabled(False)


_RECEIPT_METHOD_KEYS = [
    "RECEIPT_CASH",
    "RECEIPT_BANK",
    "RECEIPT_CHECK",
    "RECEIPT_DISCOUNT",
    "RECEIPT_GOODS_COUPON",
    "RECEIPT_VOUCHER",
    "RECEIPT_NETTING",
]
_PAYMENT_METHOD_KEYS = [
    "PAYMENT_CASH",
    "PAYMENT_BANK",
    "PAYMENT_CHECK",
    "PAYMENT_DISCOUNT",
    "PAYMENT_CHECK_DISBURSEMENT",
    "PAYMENT_NETTING",
]
_METHOD_KEYS_BY_DIRECTION = {"RECEIPT": _RECEIPT_METHOD_KEYS, "PAYMENT": _PAYMENT_METHOD_KEYS}

# طبقِ درخواستِ صریح: «برایِ هرِ مرحله یک ردیفِ جداگانه در تنظیمات باشه» —
# این کلیدها مستقل از کلیدهایِ روش‌هایِ بالا (حتی اگر عملاً به همان حساب
# اشاره کنند)، مخصوصِ مراحلِ چرخه‌یِ چکِ دریافتی/پرداختی‌اند. مرحله‌یِ
# «برگشت به طرفِ‌حساب» و «برگشتِ چکِ خرجی به صندوق» این‌جا نیستند — چون
# دو طرفِ سندشان کاملاً پویاست (طرفِ‌حسابِ اصلی/محلِ فعلیِ خودِ چک)،
# حسابِ کلِ تازه لازم ندارند؛ فقط متنِ شرحشان پایین‌تر قابلِ‌ویرایش است.
_CHECK_STAGE_MAPPING_KEYS = [
    "CHECK_RECEIVED_FUND_TRANSFER",
    "CHECK_RECEIVED_CASH_COLLECT",
    "CHECK_RECEIVED_BANK_DEPOSIT",
    "CHECK_RECEIVED_BANK_CLEAR",
    "CHECK_RECEIVED_BANK_RETURN",
    "CHECK_ISSUED_BANK_CLEAR",
    "CHECK_ISSUED_RETURN_TO_FUND",
]
_CHECK_STAGE_TEMPLATE_KEYS = ["CHECK_RECEIVED_CUSTOMER_RETURN", "CHECK_RECEIVED_ENDORSED_RETURN"]

# طبقِ گزارشِ صریح: حسابِ پیش‌پرداختِ تنخواه‌گردان باید این‌جا (تنظیماتِ
# خزانه‌داری) تعیین شود، نه در خودِ فرمِ عملیاتیِ تنخواه.
_PETTY_CASH_MAPPING_KEY = "PETTY_CASH_ADVANCE"


class TreasuryCounterpartySettingsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.company_id: int | None = None
        self._forms: dict[str, _MappingForm] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._method_mapping_containers: dict[str, QVBoxLayout] = {}
        self._method_mapping_rows: dict[str, list[_MultiAccountMappingRow]] = {"RECEIPT": [], "PAYMENT": []}
        self._template_containers: dict[str, QVBoxLayout] = {}
        self._template_rows: dict[str, list[_TemplateRow]] = {"RECEIPT": [], "PAYMENT": []}
        self._stage_mapping_rows: list[_MethodMappingRow] = []
        self._stage_template_rows: list[_TemplateRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("انواعِ سندِ دریافت/پرداخت")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        help_fields: list[tuple[QWidget, str]] = []
        for direction, section_title, account_col_title, hint in (
            (
                "RECEIPT",
                "انواعِ سندِ دریافت",
                "معینِ حسابِ بستانکار",
                "برایِ هر نوعِ تفصیلی (مثلاً «مشتری»)، معینِ حسابی که سمتِ بستانکارِ سندِ دریافت می‌شود را مشخص کنید.",
            ),
            (
                "PAYMENT",
                "انواعِ سندِ پرداخت",
                "معینِ حسابِ بدهکار",
                "برایِ هر نوعِ تفصیلی (مثلاً «تامین‌کننده»)، معینِ حسابی که سمتِ بدهکارِ سندِ پرداخت می‌شود را مشخص کنید.",
            ),
        ):
            card = QWidget()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(6)

            card_title = QLabel(section_title)
            card_title.setObjectName("sectionHint")
            card_layout.addWidget(card_title)

            form = _MappingForm(direction, self)
            card_layout.addWidget(form)
            self._forms[direction] = form

            table = QTableWidget(0, 2)
            table.setHorizontalHeaderLabels(["نوعِ تفصیلی", account_col_title])
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            table.setMinimumHeight(140)
            table.cellDoubleClicked.connect(lambda row, _col, d=direction: self._delete_mapping(d, row))
            card_layout.addWidget(table, stretch=1)
            self._tables[direction] = table

            layout.addWidget(card, stretch=1)
            help_fields.append((form, hint))
            help_fields.append((table, "برایِ حذفِ یک ردیف، رویِ آن دابل‌کلیک کنید."))

        # --- روش‌هایِ ردیفِ پایینِ سندِ دریافت/پرداخت ---------------------------
        # طبقِ درخواستِ صریح: طرفِ بستانکارِ ردیف‌هایِ دریافت (نقد/بانک/چک/
        # تخفیف/تهاتر) و طرفِ بدهکارِ ردیف‌هایِ پرداخت (همان‌ها + پرداخت با
        # چکِ دریافتی) هم این‌جا تعریف شوند.
        for direction, method_card_title, method_hint in (
            (
                "RECEIPT",
                "روش‌هایِ ردیفِ پایینِ سندِ دریافت (نقد/بانک/چک/تخفیف/کالابرگ/بن/تهاتر)",
                "معینِ سمتِ بستانکارِ ردیف‌هایِ روشِ سندِ دریافت. تفصیلیِ اختصاصی اختیاری است — اگر تعیین شود، دیگر در فرمِ سند پرسیده نمی‌شود؛ اگر خالی بماند، خودِ کاربر در فرمِ سند انتخاب می‌کند.",
            ),
            (
                "PAYMENT",
                "روش‌هایِ ردیفِ پایینِ سندِ پرداخت (نقد/بانک/چک/تخفیف/خرجِ چک/تهاتر)",
                "معینِ سمتِ بدهکارِ ردیف‌هایِ روشِ سندِ پرداخت. تفصیلیِ اختصاصی اختیاری است — اگر تعیین شود، دیگر در فرمِ سند پرسیده نمی‌شود؛ اگر خالی بماند، خودِ کاربر در فرمِ سند انتخاب می‌کند.",
            ),
        ):
            method_card = QWidget()
            method_card.setObjectName("card")
            method_card_layout = QVBoxLayout(method_card)
            method_card_layout.setContentsMargins(12, 10, 12, 10)
            method_card_layout.setSpacing(4)

            method_title = QLabel(method_card_title)
            method_title.setObjectName("sectionHint")
            method_card_layout.addWidget(method_title)

            container = QVBoxLayout()
            container.setSpacing(2)
            method_card_layout.addLayout(container)

            # طبقِ آیتمِ ۷: زیرِ فهرستِ روش‌هایِ ثابت، فرمِ افزودنِ روشِ
            # سفارشی — خودِ روش‌هایِ سفارشیِ موجود هم در همین container
            # (بعدِ روش‌هایِ ثابت) در refresh() اضافه می‌شوند.
            custom_form = _CustomMethodForm(direction, self)
            method_card_layout.addWidget(custom_form)

            layout.addWidget(method_card)
            self._method_mapping_containers[direction] = container
            help_fields.append((method_card, method_hint))
            help_fields.append(
                (custom_form, "روشِ سفارشیِ تازه (مثلِ نقد/تخفیف/بن: فقط مبلغ + تفصیلیِ اختیاری) اضافه می‌کند.")
            )

        # --- مراحلِ چرخه‌یِ چکِ دریافتی/پرداختی ----------------------------
        # طبقِ درخواستِ صریح: برایِ هرِ مرحله‌یِ چرخه‌یِ چک (انتقال بینِ
        # صندوق‌ها، وصولِ نقدی، واگذاری به بانک، اعلامِ وصول، برگشت از بانک
        # به صندوق، وصول از بانک، برگشتِ چکِ پرداختی) یک ردیفِ مستقل با
        # حسابِ کلِ/تفصیلیِ اختصاصیِ خودش.
        stage_card = QWidget()
        stage_card.setObjectName("card")
        stage_card_layout = QVBoxLayout(stage_card)
        stage_card_layout.setContentsMargins(12, 10, 12, 10)
        stage_card_layout.setSpacing(4)

        stage_title = QLabel("مراحلِ چرخه‌یِ چکِ دریافتی/پرداختی")
        stage_title.setObjectName("sectionHint")
        stage_card_layout.addWidget(stage_title)

        stage_hint = QLabel(
            "برایِ هر مرحله از چرخه‌یِ چک، معینِ حسابی که آن مرحله بدهکار می‌کند مشخص کنید. "
            "تفصیلیِ اختصاصی اختیاری است — چون معمولاً هربار صندوق/بانکِ متفاوتی انتخاب می‌شود."
        )
        stage_hint.setWordWrap(True)
        stage_card_layout.addWidget(stage_hint)

        self._stage_mapping_container = QVBoxLayout()
        self._stage_mapping_container.setSpacing(2)
        stage_card_layout.addLayout(self._stage_mapping_container)

        stage_template_hint = QLabel(
            "این دو مرحله («برگشت به طرفِ‌حساب» و «برگشتِ چکِ خرجی به صندوق») حسابِ کلِ تازه لازم ندارند "
            "— فقط متنِ شرحِ سندشان قابلِ‌ویرایش است."
        )
        stage_template_hint.setWordWrap(True)
        stage_card_layout.addWidget(stage_template_hint)

        self._stage_template_container = QVBoxLayout()
        self._stage_template_container.setSpacing(2)
        stage_card_layout.addLayout(self._stage_template_container)

        layout.addWidget(stage_card)
        help_fields.append((stage_card, "این تنظیمات، حساب/تفصیلیِ سندهایِ صفحه‌یِ «چک‌هایِ دریافتی/پرداختی» را مشخص می‌کنند."))

        # --- حسابِ پیش‌پرداختِ تنخواه‌گردان ------------------------------------
        petty_cash_card = QWidget()
        petty_cash_card.setObjectName("card")
        petty_cash_card_layout = QVBoxLayout(petty_cash_card)
        petty_cash_card_layout.setContentsMargins(12, 10, 12, 10)
        petty_cash_card_layout.setSpacing(4)

        petty_cash_title = QLabel("تنخواه‌گردان")
        petty_cash_title.setObjectName("sectionHint")
        petty_cash_card_layout.addWidget(petty_cash_title)

        petty_cash_hint = QLabel(
            "معینِ حسابی که در افتتاحِ هر تنخواه بدهکار، و در بستنِ آن بستانکار می‌شود؛ "
            "این حساب برایِ همه‌یِ تنخواه‌دارها مشترک است."
        )
        petty_cash_hint.setWordWrap(True)
        petty_cash_card_layout.addWidget(petty_cash_hint)

        self._petty_cash_mapping_container = QVBoxLayout()
        self._petty_cash_mapping_container.setSpacing(2)
        petty_cash_card_layout.addLayout(self._petty_cash_mapping_container)

        layout.addWidget(petty_cash_card)
        help_fields.append((petty_cash_card, "این تنظیم، حسابِ معینِ فرمِ «تنخواه‌گردان» را مشخص می‌کند."))

        # --- متنِ خودکارِ شرحِ ردیف‌هایِ سندِ دریافت/پرداخت -------------------
        # طبقِ درخواستِ صریح («مدلِ تنظیماتِ روش‌هایِ پرداخت مثلِ روش‌هایِ
        # دریافت»): کاربر خودش می‌تواند متنِ هر روش را بسازد — برایِ هر دو
        # جهت، نه فقط دریافت.
        for direction, template_card_title, template_hint_text in (
            (
                "RECEIPT",
                "متنِ خودکارِ شرحِ ردیف‌هایِ سندِ دریافت",
                "جای‌گذارهایِ مجاز: {تفصیلی} (تفصیلیِ خودِ ردیف)، {مبلغ}، {طرف_حساب} (تفصیلیِ بالایِ فرم)، "
                "{تعداد} (فقط چک)، {یادداشت} (فقط بن).",
            ),
            (
                "PAYMENT",
                "متنِ خودکارِ شرحِ ردیف‌هایِ سندِ پرداخت",
                "جای‌گذارهایِ مجاز: {تفصیلی} (تفصیلیِ خودِ ردیف)، {مبلغ}، {طرف_حساب} (تفصیلیِ بالایِ فرم)، "
                "{تعداد} (فقط چک/خرجِ چک).",
            ),
        ):
            template_card = QWidget()
            template_card.setObjectName("card")
            template_card_layout = QVBoxLayout(template_card)
            template_card_layout.setContentsMargins(12, 10, 12, 10)
            template_card_layout.setSpacing(4)

            template_title = QLabel(template_card_title)
            template_title.setObjectName("sectionHint")
            template_card_layout.addWidget(template_title)

            template_hint = QLabel(template_hint_text)
            template_hint.setWordWrap(True)
            template_card_layout.addWidget(template_hint)

            container = QVBoxLayout()
            container.setSpacing(2)
            template_card_layout.addLayout(container)
            layout.addWidget(template_card)
            self._template_containers[direction] = container
            help_fields.append((template_card, "این متن‌ها خودکار در ستونِ «شرح»ِ همان ردیف در فرمِ سند پیشنهاد می‌شوند — قابلِ‌ویرایشِ دستی هم هستند."))

        self.set_field_help(help_fields)

    def set_status(self, text: str, *, ok: bool = False) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.company_id = self._company_id()
        if self.company_id is None:
            return
        company_id = self.company_id

        group_options: list[tuple[tuple[str, int], str]] = []
        for g in dimensions_service.list_person_groups(company_id):
            group_options.append((("person", g.person_group_id), g.name))
        for t in dimensions_service.list_dimension_types(company_id):
            label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(t.code, t.code)
            group_options.append((("dim", t.dimension_type_id), label))

        account_options = [(a.account_id, f"{a.full_code} — {a.name}") for a in coa_service.list_postable_accounts(company_id)]

        for direction, form in self._forms.items():
            form.set_options(group_options, account_options)
            self.refresh_mappings(direction)

        method_mappings_by_key = {m.mapping_key: m for m in treasury_service.list_account_mappings(company_id)}
        detail_options = [
            (d.detail_account_id, f"{d.full_code} — {d.name}" if d.name else d.full_code)
            for d in dimensions_service.list_all_leaf_detail_accounts(company_id)
        ]
        for direction, container in self._method_mapping_containers.items():
            while container.count():
                child = container.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            self._method_mapping_rows[direction] = []
            for key in _METHOD_KEYS_BY_DIRECTION[direction]:
                # طبقِ درخواستِ صریح («مدلِ تنظیماتِ روش‌هایِ پرداخت مثلِ
                # روش‌هایِ دریافت»): هر دو جهت می‌توانند چند معین داشته باشند.
                mapped = treasury_service.list_mapped_accounts_for_key(company_id, key)
                row = _MultiAccountMappingRow(
                    key,
                    treasury_service.MAPPING_LABELS[key],
                    [m.account_id for m in mapped],
                    {m.account_id: m.detail_account_id for m in mapped if m.detail_account_id is not None},
                    account_options,
                    detail_options,
                    self._save_multi_method_mapping,
                )
                container.addWidget(row)
                self._method_mapping_rows[direction].append(row)

            # طبقِ آیتمِ ۷: بعدِ روش‌هایِ ثابت، روش‌هایِ سفارشیِ همین شرکت/
            # جهت — هر روش، یک ردیفِ مدیریت (نام/فعال/حذف) + بلافاصله
            # زیرش، یک ردیفِ نگاشتِ حساب (عیناً هم‌الگو با روش‌هایِ ثابت).
            for custom_method in treasury_service.list_custom_methods(company_id, direction):
                management_row = _CustomMethodRow(custom_method, self._toggle_custom_method, self._delete_custom_method)
                container.addWidget(management_row)
                mapping_key = treasury_service.custom_method_mapping_key(direction, custom_method.custom_method_id)
                mapped = treasury_service.list_mapped_accounts_for_key(company_id, mapping_key)
                mapping_row = _MultiAccountMappingRow(
                    mapping_key,
                    f"معینِ «{custom_method.label}»",
                    [m.account_id for m in mapped],
                    {m.account_id: m.detail_account_id for m in mapped if m.detail_account_id is not None},
                    account_options,
                    detail_options,
                    self._save_multi_method_mapping,
                )
                container.addWidget(mapping_row)
                self._method_mapping_rows[direction].append(mapping_row)

        for direction, container in self._template_containers.items():
            while container.count():
                child = container.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            self._template_rows[direction] = []
            for t in treasury_service.list_description_templates(company_id, direction):
                row = _TemplateRow(t.template_key, t.label, t.template_text, self._save_template)
                container.addWidget(row)
                self._template_rows[direction].append(row)

        while self._stage_mapping_container.count():
            child = self._stage_mapping_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._stage_mapping_rows = []
        for key in _CHECK_STAGE_MAPPING_KEYS:
            mapping = method_mappings_by_key.get(key)
            row = _MethodMappingRow(
                key,
                treasury_service.MAPPING_LABELS[key],
                mapping.account_id if mapping else None,
                mapping.detail_account_id if mapping else None,
                account_options,
                detail_options,
                self._save_method_mapping,
            )
            self._stage_mapping_container.addWidget(row)
            self._stage_mapping_rows.append(row)

        while self._stage_template_container.count():
            child = self._stage_template_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._stage_template_rows = []
        for key in _CHECK_STAGE_TEMPLATE_KEYS:
            row = _TemplateRow(
                key, treasury_service.MAPPING_LABELS[key], treasury_service.get_description_template(company_id, key),
                self._save_template,
            )
            self._stage_template_container.addWidget(row)
            self._stage_template_rows.append(row)

        while self._petty_cash_mapping_container.count():
            child = self._petty_cash_mapping_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        petty_cash_account_id = treasury_service.get_account_mapping(company_id, _PETTY_CASH_MAPPING_KEY)
        petty_cash_row = _MethodMappingRow(
            _PETTY_CASH_MAPPING_KEY, treasury_service.MAPPING_LABELS[_PETTY_CASH_MAPPING_KEY],
            petty_cash_account_id, None, account_options, [], self._save_method_mapping,
        )
        petty_cash_row.detail_combo.setVisible(False)
        self._petty_cash_mapping_container.addWidget(petty_cash_row)

    def _save_method_mapping(self, mapping_key: str, account_id, detail_account_id) -> bool:
        if self.company_id is None or account_id is None:
            self.set_status("ابتدا یک حساب انتخاب کنید.")
            return False
        treasury_service.set_account_mapping(self.company_id, mapping_key, account_id, detail_account_id)
        self.set_status("ذخیره شد.", ok=True)
        return True

    def _save_multi_method_mapping(self, mapping_key: str, account_ids: list[int], detail_account_id: int | None) -> bool:
        """طبقِ آیتمِ ۹: ذخیره‌یِ چندمعینیِ روش‌هایِ دریافت — تفصیلیِ
        اختصاصی فقط وقتی معنی دارد که دقیقاً یک معین انتخاب شده باشد."""
        if self.company_id is None:
            return False
        if not account_ids:
            self.set_status("حداقلِ یک معین انتخاب کنید.")
            return False
        entries = [(account_id, detail_account_id if account_id == account_ids[0] else None) for account_id in account_ids]
        treasury_service.set_account_mappings(self.company_id, mapping_key, entries)
        self.set_status("ذخیره شد.", ok=True)
        return True

    def _toggle_custom_method(self, custom_method_id: int, is_active: bool) -> None:
        if self.company_id is None:
            return
        treasury_service.set_custom_method_active(self.company_id, custom_method_id, is_active)
        self.set_status("ذخیره شد.", ok=True)

    def _delete_custom_method(self, custom_method_id: int) -> None:
        if self.company_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ روشِ سفارشی", "این روشِ سفارشی حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        treasury_service.delete_custom_method(self.company_id, custom_method_id)
        self.set_status("حذف شد.", ok=True)
        self.refresh()

    def _save_template(self, template_key: str, text: str) -> bool:
        if self.company_id is None:
            return False
        treasury_service.set_description_template(self.company_id, template_key, text)
        self.set_status("ذخیره شد.", ok=True)
        return True

    def refresh_mappings(self, direction: str) -> None:
        if self.company_id is None:
            return
        table = self._tables[direction]
        rows = treasury_service.list_counterparty_mappings(self.company_id, direction)
        table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            values = [r.group_label, r.account_label]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.mapping_id)
                table.setItem(row_index, col_index, item)

    def _delete_mapping(self, direction: str, row: int) -> None:
        if self.company_id is None:
            return
        table = self._tables[direction]
        mapping_id = table.item(row, 0).data(Qt.UserRole)
        confirm = QMessageBox.question(
            self, "حذفِ ردیف", "این نگاشت حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        treasury_service.delete_counterparty_mapping(mapping_id, self.company_id)
        self.refresh_mappings(direction)
