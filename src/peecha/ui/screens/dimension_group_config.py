"""پیکربندیِ گروه‌هایِ تفصیلی — ساختِ گروهِ تازه + تنظیمِ تعدادِ سطح/بازه‌یِ
از-تا/فیلدهایِ اختصاصیِ هر گروه (تا ۴ سطح). طبقِ درخواستِ صریح، تعدادِ رقمِ
هر سطح سراسری شده (تنظیماتِ «کدینگِ حسابداری») و اینجا فقط بازه و سقفِ
تعدادِ سطحِ هر گروه تنظیم می‌شود.

طبقِ درخواستِ صریح: این بخش از صفحه‌ی قدیمیِ سه‌ستونیِ «مراکزِ هزینه و
ابعادِ تفصیلی» جدا شده — آن صفحه فقط به ثبتِ خودِ حساب‌هایِ تفصیلیِ
گروه‌هایِ «ساده» (بدونِ صفحه‌ی اختصاصی) محدود شده، و ساختِ گروه/پیکربندیِ
سطوح این‌جا آمده. گروه‌هایِ «فرمِ خاص» (کالا/دارایی‌ثابت/بانک/صندوق/
تنخواه/مرکزِ هزینه/پروژه) هم این‌جا قابلِ‌پیکربندی‌اند (چون سطوح/فیلدهایِ
اختصاصیِ آن‌ها هم از همین acc.detail_group_levels/detail_group_fields
می‌آید)، فقط ثبتِ خودِ حساب‌هایشان در صفحه‌ی اختصاصیِ خودشان انجام می‌شود.

طبقِ درخواستِ صریحِ بعدی: «همه گروه‌های تفصیلی حتی مشتری/تامین‌کننده/
پرسنل» هم باید این‌جا قابلِ‌پیکربندی باشند. مشکل: این سه، برخلافِ بقیه،
یک نوع‌بُعدِ مستقل نیستند — هرسه زیرِ همان نوع‌بُعدِ سیستمیِ PERSON‌اند و
فقط با person_group_id از هم جدا می‌شوند (acc.person_groups). پس هر
آیتمِ این فهرست حالا یک سه‌تایی نگه می‌دارد: (dimension_type_id,
person_group_id, برچسبِ نمایشی) — برایِ گروه‌هایِ معمولی person_group_id
همیشه ۰ (بدونِ محدودیت) است؛ برایِ مشتری/تامین‌کننده/پرسنل، همه
dimension_type_id یکسان (PERSON) ولی person_group_id واقعیِ خودشان را
دارند تا acc.detail_group_levels/detail_group_fields (که با ستونِ تازه‌ی
person_group_id کلید می‌خورند) مستقل از هم پیکربندی شوند."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import detail_dimensions as dimensions_service
from peecha.ui import theme
from peecha.ui.widgets import FieldHelpMixin, ZeroPaddedSpinBox

_FIELD_KIND_OPTIONS = [
    ("text", "متن"),
    ("decimal", "عدد اعشاری"),
    ("date", "تاریخ"),
    ("boolean", "بله/خیر"),
    ("bank", "بانک (از فهرستِ بانک‌ها)"),
    ("account_type", "نوعِ حساب (جاری/پس‌انداز)"),
]
_LEVEL_COUNT = 4

_PERSON_GROUP_LIST_FUNCS = {
    dimensions_service.CUSTOMER_GROUP_CODE: dimensions_service.list_customers,
    dimensions_service.SUPPLIER_GROUP_CODE: dimensions_service.list_suppliers,
    dimensions_service.PERSONNEL_GROUP_CODE: dimensions_service.list_personnel,
}


class _GroupFieldRowWidget(QWidget):
    def __init__(self, on_remove, initial: dimensions_service.GroupFieldRow | None = None) -> None:
        super().__init__()
        self._on_remove = on_remove
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.key_field = QLineEdit()
        self.key_field.setPlaceholderText("کلید (مثلاً account_no)")
        layout.addWidget(self.key_field)

        self.label_field = QLineEdit()
        self.label_field.setPlaceholderText("عنوان")
        layout.addWidget(self.label_field)

        self.kind_combo = QComboBox()
        for code, label in _FIELD_KIND_OPTIONS:
            self.kind_combo.addItem(label, code)
        layout.addWidget(self.kind_combo)

        self.required_checkbox = QCheckBox("اجباری")
        layout.addWidget(self.required_checkbox)

        remove_button = QPushButton("حذف")
        remove_button.setObjectName("dangerButton")
        remove_button.clicked.connect(lambda: self._on_remove(self))
        layout.addWidget(remove_button)

        if initial is not None:
            self.key_field.setText(initial.field_key)
            self.label_field.setText(initial.label)
            index = self.kind_combo.findData(initial.kind)
            self.kind_combo.setCurrentIndex(index if index >= 0 else 0)
            self.required_checkbox.setChecked(initial.is_required)

    def to_field_dict(self, sort_order: int) -> dict:
        return {
            "field_key": self.key_field.text().strip(),
            "label": self.label_field.text().strip(),
            "kind": self.kind_combo.currentData(),
            "is_required": self.required_checkbox.isChecked(),
            "sort_order": sort_order,
        }


class DimensionGroupConfigScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._types: list[dimensions_service.DimensionTypeRow] = []
        self._selected_type_id: int | None = None
        self._selected_person_group_id: int = 0
        self._field_rows: list[_GroupFieldRowWidget] = []
        self._current_color: str | None = None

        # طبقِ گزارشِ صریح: قبلاً فهرستِ گروه‌ها و فرمِ پیکربندی کنارِ هم
        # (چیدمانِ افقی) بودند — این باعث می‌شد فرمِ پیکربندی (که خودش
        # چندین ستون دارد: سطح/از/تا) عرضِ کافی نداشته باشد و علاوه بر
        # اسکرولِ عمودی، اسکرولِ افقی هم لازم شود. حالا فهرستِ گروه‌ها
        # یک نوارِ باریک/افقیِ ثابت‌ارتفاع در بالا است و فرمِ پیکربندی
        # تمامِ عرضِ صفحه را در اختیار دارد (فقط اسکرولِ عمودی، طبقِ
        # استانداردِ ریسپانسیو).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_types_panel())
        outer.addWidget(self._build_config_panel(), stretch=1)

        level_help = [
            (
                widgets[0],
                f"کمترین کدِ مجاز برایِ سطحِ {level_no} از این گروه. صفر یعنی بدونِ محدودیتِ ابتدا.",
            )
            for level_no, widgets in self._level_widgets.items()
        ] + [
            (
                widgets[1],
                f"بیشترین کدِ مجاز برایِ سطحِ {level_no} از این گروه. صفر یعنی بدونِ محدودیتِ انتها.",
            )
            for level_no, widgets in self._level_widgets.items()
        ]
        self.set_field_help([
            (
                self.new_type_code_field,
                "کدِ گروهِ تفصیلیِ تازه‌ای که می‌خواهید بسازید، مثلاً «مرکزِ فروش». بعدِ کلیکِ «افزودنِ گروه» ساخته می‌شود.",
            ),
            (
                self.types_list,
                "فهرستِ همه‌یِ گروه‌هایِ تفصیلی — کالا، بانک، مرکزِ هزینه، مشتری و مانندِ آن. "
                "رویِ هرکدام کلیک کنید تا پیکربندی‌اش را پایین ببینید و تغییر دهید.",
            ),
            (
                self.title_field,
                "نامِ نمایشیِ این گروه. برایِ گروه‌هایِ سیستمی مثلِ کالا و بانک قابلِ‌تغییر نیست، "
                "چون نامشان ثابت است. برایِ گروه‌هایِ دلخواه همیشه قابلِ‌تغییر است.",
            ),
            (
                self.max_level_spin,
                "این گروه چند سطح دارد، حداکثر تا ۴ سطح. مثلاً «مرکزِ هزینه» می‌تواند دو سطح داشته باشد: "
                "دسته‌یِ کلی و زیرِمجموعه‌اش. اگر حساب‌هایِ این گروه سند داشته باشند، این عدد دیگر قابلِ‌تغییر نیست.",
            ),
            *level_help,
        ])

    # --- نوارِ بالا: گروه‌ها (افقی) ------------------------------------------
    def _build_types_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        panel.setMaximumHeight(190)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        title = QLabel("گروه‌هایِ تفصیلی")
        title.setObjectName("pageTitle")
        header_row.addWidget(title)
        header_row.addStretch(1)
        header_row.addWidget(QLabel("کدِ گروهِ تازه"))
        self.new_type_code_field = QLineEdit()
        self.new_type_code_field.setFixedWidth(160)
        header_row.addWidget(self.new_type_code_field)
        create_button = QPushButton("افزودنِ گروه")
        create_button.setObjectName("primaryButton")
        create_button.clicked.connect(self._create_type)
        header_row.addWidget(create_button)
        layout.addLayout(header_row)

        hint = QLabel(
            "کالا/دارایی‌ثابت/بانک/صندوق/تنخواه/مرکزِ هزینه/پروژه + مشتری/تامین‌کننده/پرسنل + گروه‌هایِ ساده‌یِ دلخواه."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # طبقِ درخواستِ صریح: فهرستِ گروه‌ها به‌جایِ ستونِ عمودیِ بلند،
        # به‌صورتِ افقی (چیده‌شده/wrap‌شونده در چند ردیف) نمایش داده
        # می‌شود — با ارتفاعِ ثابت، خودش در صورتِ زیادبودنِ گروه‌ها
        # عمودی اسکرول می‌کند، بدونِ آنکه به فرمِ پیکربندیِ زیرش فشار بیاورد.
        self.types_list = QListWidget()
        self.types_list.setFlow(QListWidget.LeftToRight)
        self.types_list.setWrapping(True)
        self.types_list.setResizeMode(QListWidget.Adjust)
        self.types_list.setFixedHeight(72)
        self.types_list.itemClicked.connect(self._on_type_selected)
        layout.addWidget(self.types_list)

        self.type_status_label = QLabel("")
        self.type_status_label.setObjectName("statusError")
        self.type_status_label.setWordWrap(True)
        layout.addWidget(self.type_status_label)

        return panel

    # --- ستونِ ۲: پیکربندیِ سطوح/فیلدها --------------------------------------
    def _build_config_panel(self) -> QWidget:
        # طبقِ گزارشِ صریح: این پنل فیلدِ اختصاصیِ نامحدود (کاربر می‌تواند
        # هر تعداد «+ افزودنِ فیلد» بزند) دارد و هیچ اسکرولی نداشت — با
        # فیلدهایِ زیاد یا فونتِ بلندتر، دکمه‌ی «ذخیره‌یِ فیلدها» و حتی
        # بخش‌هایِ بالاترِ فرم از دیدرس خارج می‌شدند و هیچ راهی برایِ
        # رسیدن به آن‌ها نبود. حالا کلِ محتوایِ این پنل درونِ یک
        # QScrollArea قرار گرفته — همان الگویی که accounting_coding.py
        # از اول داشت.
        scroll = QScrollArea()
        scroll.setObjectName("card")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.config_panel = scroll
        scroll.setEnabled(False)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.config_title = QLabel("پیکربندیِ گروه")
        self.config_title.setObjectName("pageTitle")
        layout.addWidget(self.config_title)

        self.lock_hint_label = QLabel("")
        self.lock_hint_label.setObjectName("sectionHint")
        self.lock_hint_label.setWordWrap(True)
        layout.addWidget(self.lock_hint_label)

        # طبقِ درخواستِ صریح: عنوانِ گروه در هر شرایطی (حتی اگر حساب‌هایِ
        # تفصیلی‌اش سند داشته باشند) باید قابلِ‌اصلاح باشد — بر خلافِ
        # سطح/بازه که بعدِ سنددارشدنِ همین گروه قفل می‌شود. برایِ ۷ نوعِ
        # سیستمی (کالا/بانک/...) این فیلد غیرفعال می‌ماند چون عنوانشان
        # ثابت/سیستمی است (نه چیزی که مدیر تعریف کرده باشد).
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("عنوانِ گروه"))
        self.title_field = QLineEdit()
        title_row.addWidget(self.title_field, stretch=1)
        save_title_button = QPushButton("ذخیره‌یِ عنوان")
        save_title_button.setObjectName("flatButton")
        save_title_button.clicked.connect(self._save_title)
        title_row.addWidget(save_title_button)
        layout.addLayout(title_row)

        # طبقِ گزارشِ صریح («نشان دهد چه معین‌هایی به گروهِ هزینه/تفصیلی
        # وصل‌اند»): فهرستِ همان معین‌هایی که این گروه را در چک‌لیستِ
        # کدینگِ حسابداری الزامی کرده‌اند.
        self.linked_accounts_label = QLabel("")
        self.linked_accounts_label.setObjectName("sectionHint")
        self.linked_accounts_label.setWordWrap(True)
        layout.addWidget(self.linked_accounts_label)

        # طبقِ درخواستِ صریح: گروهِ سادهِ کاربرساخته که هیچ‌کدام از
        # حساب‌هایِ تفصیلی‌اش سند ندارند، باید کاملاً قابلِ‌حذف باشد.
        delete_row = QHBoxLayout()
        delete_row.addStretch(1)
        self.delete_group_button = QPushButton("حذفِ کاملِ این گروه")
        self.delete_group_button.setObjectName("dangerButton")
        self.delete_group_button.clicked.connect(self._delete_group)
        delete_row.addWidget(self.delete_group_button)
        layout.addLayout(delete_row)

        # طبقِ درخواستِ صریح: هر گروهِ تفصیلی می‌تواند رنگِ اختصاصیِ خودش را
        # داشته باشد — این رنگ در فهرستِ تفصیلی‌ها (نمایِ درختی) و کمبویِ
        # تفصیلیِ فرمِ صدورِ سند هم استفاده می‌شود.
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("رنگِ این گروه"))
        self.color_button = QPushButton("")
        self.color_button.setFixedSize(30, 26)
        self.color_button.clicked.connect(self._pick_color)
        color_row.addWidget(self.color_button)
        clear_color_button = QPushButton("حذفِ رنگ")
        clear_color_button.setObjectName("flatButton")
        clear_color_button.clicked.connect(self._clear_color)
        color_row.addWidget(clear_color_button)
        color_row.addStretch(1)
        layout.addLayout(color_row)

        # طبقِ درخواستِ صریح: «کدام گروه(هایِ) تفصیلی = پرسنل» باید از
        # همین صفحه‌یِ تنظیماتِ گروه‌هایِ تفصیلی کنترل شود، نه هاردکد در
        # کد — فقط برایِ گروه‌هایِ سیستمیِ اشخاص (مشتری/تامین‌کننده/پرسنل)
        # معنی دارد، پس فقط برایِ آن‌ها نمایان می‌شود.
        self.is_personnel_checkbox = QCheckBox(
            "این گروه پرسنل است (تعریفِ کارکنان از همین گروه انجام می‌شود)"
        )
        self.is_personnel_checkbox.toggled.connect(self._on_is_personnel_toggled)
        layout.addWidget(self.is_personnel_checkbox)

        # طبقِ بازخوردِ کاربر: قبلاً «تعدادِ سطح» و «بازه‌ی سطوح» دو دکمه‌ی
        # ذخیره‌یِ جدا داشتند — کاربر با کلیک‌کردنِ فقط دکمه‌یِ کنارِ «تعدادِ
        # سطح» (چون همان‌جا، کنارِ فیلدی که تازه تغییرش داده، در دسترس‌تر
        # بود) گمان می‌کرد همه‌چیز ذخیره شده، درحالی‌که بازه‌یِ سطوح هنوز
        # ذخیره نشده بود. حالا فقط یک دکمه‌ی ذخیره برایِ کلِ این بخش هست تا
        # دیگر امکانِ «ذخیره‌ی نصفه» وجود نداشته باشد.
        max_level_row = QHBoxLayout()
        max_level_row.addWidget(QLabel("تعدادِ سطحِ این گروه"))
        self.max_level_spin = QSpinBox()
        self.max_level_spin.setRange(1, _LEVEL_COUNT)
        self.max_level_spin.valueChanged.connect(self._on_max_level_changed)
        max_level_row.addWidget(self.max_level_spin)
        max_level_row.addStretch(1)
        layout.addLayout(max_level_row)

        # طبقِ گزارشِ صریح: نبودِ setWordWrap رویِ این برچسبِ طولانی، عرضِ
        # کلِ پنل را (برایِ جادادنِ متن در یک خط) بیش‌ازحد زیاد می‌کرد —
        # همان علتِ اسکرولِ افقیِ ناخواسته.
        range_hint = QLabel(
            "بازه‌ی از-تا برایِ هر سطح (صفر = بدونِ محدودیت) — تعدادِ رقمِ هر سطح سراسری است و در "
            "تنظیماتِ «کدینگِ حسابداری» مشخص می‌شود، این‌جا فقط بازه مخصوصِ همین گروه است."
        )
        range_hint.setWordWrap(True)
        layout.addWidget(range_hint)
        levels_grid = QGridLayout()
        levels_grid.setSpacing(6)
        levels_grid.addWidget(QLabel("سطح"), 0, 0)
        levels_grid.addWidget(QLabel("از"), 0, 1)
        levels_grid.addWidget(QLabel("تا"), 0, 2)
        self._level_widgets: dict[int, tuple[ZeroPaddedSpinBox, ZeroPaddedSpinBox]] = {}
        for row, level_no in enumerate(range(1, _LEVEL_COUNT + 1), start=1):
            levels_grid.addWidget(QLabel(f"سطحِ {level_no}"), row, 0)
            range_from = ZeroPaddedSpinBox()
            range_from.setRange(0, 999_999_999)
            range_to = ZeroPaddedSpinBox()
            range_to.setRange(0, 999_999_999)
            # طبقِ درخواستِ صریح: بصورتِ زنده (حینِ تایپ، پیش از ذخیره) اگر
            # بازه با بازه‌ی گروهِ دیگری هم‌پوشانی داشته باشد قرمز، وگرنه
            # سبز — تا کاربر پیش از کلیکِ «ذخیره» متوجهِ تداخل بشود.
            range_from.valueChanged.connect(lambda _v, lvl=level_no: self._validate_range_live(lvl))
            range_to.valueChanged.connect(lambda _v, lvl=level_no: self._validate_range_live(lvl))
            levels_grid.addWidget(range_from, row, 1)
            levels_grid.addWidget(range_to, row, 2)
            self._level_widgets[level_no] = (range_from, range_to)
        layout.addLayout(levels_grid)

        self.save_levels_button = QPushButton("ذخیره‌یِ تعدادِ سطح و بازه‌یِ سطوح")
        self.save_levels_button.setObjectName("primaryButton")
        self.save_levels_button.clicked.connect(self._save_levels)
        layout.addWidget(self.save_levels_button)

        layout.addWidget(QLabel("فیلدهایِ اختصاصیِ این گروه"))
        self.fields_container = QVBoxLayout()
        fields_widget = QWidget()
        fields_widget.setLayout(self.fields_container)
        layout.addWidget(fields_widget)

        add_field_button = QPushButton("+ افزودنِ فیلد")
        add_field_button.setObjectName("flatButton")
        add_field_button.clicked.connect(lambda: self._add_field_row())
        layout.addWidget(add_field_button)

        save_fields_button = QPushButton("ذخیره‌ی فیلدها")
        save_fields_button.setObjectName("primaryButton")
        save_fields_button.clicked.connect(self._save_fields)
        layout.addWidget(save_fields_button)

        layout.addStretch(1)
        scroll.setWidget(panel)
        return scroll

    # --- بارگذاری ------------------------------------------------------------
    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        self._types = dimensions_service.list_dimension_types(company_id) if company_id is not None else []
        self.types_list.clear()
        for t in self._types:
            label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(t.code, t.code)
            item = QListWidgetItem(f"{label} ({t.detail_account_count})")
            item.setData(Qt.UserRole, (t.dimension_type_id, 0, label))
            if t.color:
                item.setForeground(QBrush(QColor(t.color)))
            self.types_list.addItem(item)

        if company_id is not None:
            person_dimension_type_id = dimensions_service.get_person_dimension_type_id(company_id)
            for group in dimensions_service.list_person_groups(company_id):
                list_func = _PERSON_GROUP_LIST_FUNCS.get(group.code)
                count = len(list_func(company_id)) if list_func else 0
                item = QListWidgetItem(f"{group.name} ({count})")
                item.setData(Qt.UserRole, (person_dimension_type_id, group.person_group_id, group.name))
                if group.color:
                    item.setForeground(QBrush(QColor(group.color)))
                self.types_list.addItem(item)

        if self._selected_type_id is None:
            self.config_panel.setEnabled(False)

    def _create_type(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        code = self.new_type_code_field.text().strip()
        if not code:
            self._show_type_status("کد را وارد کنید.", ok=False)
            return
        try:
            new_type = dimensions_service.create_dimension_type(company_id, code)
        except ValueError as exc:
            self._show_type_status(str(exc), ok=False)
            return
        self._show_type_status("گروهِ تازه ایجاد شد.", ok=True)
        self.new_type_code_field.clear()
        self.refresh()
        label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(new_type.code, new_type.code)
        self._select_type(new_type.dimension_type_id, 0, label)

    def _on_type_selected(self, item: QListWidgetItem) -> None:
        dimension_type_id, person_group_id, label = item.data(Qt.UserRole)
        self._select_type(dimension_type_id, person_group_id, label)

    def _select_type(self, dimension_type_id: int, person_group_id: int = 0, label: str | None = None) -> None:
        self._selected_type_id = dimension_type_id
        self._selected_person_group_id = person_group_id
        if label is None:
            dim_type = next((t for t in self._types if t.dimension_type_id == dimension_type_id), None)
            label = (
                dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(dim_type.code, dim_type.code)
                if dim_type is not None
                else str(dimension_type_id)
            )
        self.config_title.setText(f"پیکربندیِ گروهِ «{label}»")
        self.config_panel.setEnabled(True)
        self._current_color = dimensions_service.get_group_color(dimension_type_id, person_group_id)
        self._apply_color_swatch(self._current_color)

        self.title_field.setText(label)
        dim_type = next((t for t in self._types if t.dimension_type_id == dimension_type_id), None)
        is_specialized_system_type = (
            person_group_id == 0 and dim_type is not None and dim_type.code in dimensions_service.SPECIALIZED_DIMENSION_LABELS
        )
        self.title_field.setEnabled(not is_specialized_system_type)
        self._is_custom_simple_group = (
            person_group_id == 0 and dim_type is not None and dim_type.code not in dimensions_service.SPECIALIZED_DIMENSION_LABELS
        )

        self.is_personnel_checkbox.setVisible(person_group_id != 0)
        if person_group_id != 0:
            self.is_personnel_checkbox.blockSignals(True)
            self.is_personnel_checkbox.setChecked(dimensions_service.is_personnel_group(person_group_id))
            self.is_personnel_checkbox.blockSignals(False)

        company_id = self._company_id()
        digit_config_by_level = (
            {r.level_no: r.code_length for r in dimensions_service.list_level_digit_config(company_id)}
            if company_id is not None
            else {}
        )
        for level_no, (range_from, range_to) in self._level_widgets.items():
            digits = digit_config_by_level.get(level_no) or 0
            range_from.set_digits(digits)
            range_to.set_digits(digits)

        self.max_level_spin.blockSignals(True)
        self.max_level_spin.setValue(dimensions_service.get_group_max_level_no(dimension_type_id, person_group_id))
        self.max_level_spin.blockSignals(False)
        self._saved_max_level_no = self.max_level_spin.value()
        self._update_level_save_hint()
        self._load_levels()
        self._load_fields()

        if company_id is not None:
            linked = dimensions_service.list_accounts_requiring_group(
                company_id, dimension_type_id=dimension_type_id if not person_group_id else None,
                person_group_id=person_group_id or None,
            )
            self.linked_accounts_label.setText(
                "معین‌هایِ متصل به این گروه: " + ("، ".join(linked) if linked else "هیچ‌کدام")
            )
        else:
            self.linked_accounts_label.setText("")

        has_usage = (
            company_id is not None
            and dimensions_service.group_has_any_usage(dimension_type_id, company_id, person_group_id)
        )
        locked = has_usage
        self._levels_locked = locked
        self._apply_level_enablement(self.max_level_spin.value())
        # _load_levels (بالا) رنگِ زنده را با enablementِ گروهِ قبلی محاسبه
        # کرده بود — حالا که enablementِ همین گروه اعمال شد، دوباره محاسبه می‌شود.
        for level_no in self._level_widgets:
            self._validate_range_live(level_no)
        self.save_levels_button.setEnabled(not locked)
        self.max_level_spin.setEnabled(not locked)
        self.lock_hint_label.setText(
            "حساب‌هایِ تفصیلیِ همین گروه سند دارند؛ تنظیماتِ رقم/بازه/تعدادِ سطحِ این گروه دیگر قابلِ‌تغییر نیست."
            if locked
            else ""
        )
        self.delete_group_button.setEnabled(self._is_custom_simple_group and not has_usage)

    def _on_max_level_changed(self, value: int) -> None:
        self._apply_level_enablement(value)
        for level_no in self._level_widgets:
            self._validate_range_live(level_no)
        self._update_level_save_hint()

    def _update_level_save_hint(self) -> None:
        # طبقِ گزارشِ صریح: تغییرِ «تعدادِ سطح» با تایپ/کلیکِ اسپین‌باکس به‌
        # تنهایی ذخیره نمی‌شود — کاربر باید حتماً دکمه‌یِ همین بخش را هم
        # بزند؛ قبلاً هیچ نشانه‌ای نبود که این دو از هم جدا افتاده‌اند، پس
        # کاربر فکر می‌کرد تغییر اعمال شده درحالی‌که در سطحِ آخرِ واقعیِ
        # ذخیره‌شده (که ممکن است خیلی بزرگ‌تر باشد) هنوز فیلدهایِ اختصاصیِ
        # آن سطح، غلط، در سطوحِ پایین‌تر پنهان می‌ماندند.
        unsaved = self.max_level_spin.value() != getattr(self, "_saved_max_level_no", self.max_level_spin.value())
        self.save_levels_button.setStyleSheet(
            f"border: 2px solid {theme.WARNING}; font-weight: bold;" if unsaved else ""
        )
        self.save_levels_button.setToolTip(
            "تعدادِ سطح تغییر کرده ولی هنوز ذخیره نشده — تا این دکمه را نزنید، فیلدهایِ اختصاصیِ سطحِ آخر درست نمایش داده نمی‌شوند."
            if unsaved else ""
        )

    def _apply_level_enablement(self, max_level_no: int) -> None:
        # طبقِ درخواستِ صریح: سطوحِ فراتر از سقفِ این گروه (مثلاً سطحِ ۳/۴
        # وقتی «تعدادِ سطح» ۲ تنظیم شده) غیرفعال/کم‌رنگ می‌شوند — چون این
        # گروه اصلاً نمی‌تواند حسابِ تفصیلی در آن سطوح داشته باشد.
        locked = getattr(self, "_levels_locked", False)
        for level_no, (range_from, range_to) in self._level_widgets.items():
            enabled = (not locked) and level_no <= max_level_no
            range_from.setEnabled(enabled)
            range_to.setEnabled(enabled)

    # --- سطوح ------------------------------------------------------------
    def _load_levels(self) -> None:
        rows = {
            row.level_no: row
            for row in dimensions_service.list_group_levels(self._selected_type_id, self._selected_person_group_id)
        }
        for level_no, (range_from, range_to) in self._level_widgets.items():
            row = rows.get(level_no)
            range_from.setValue(row.range_from if row and row.range_from is not None else 0)
            range_to.setValue(row.range_to if row and row.range_to is not None else 0)
            self._validate_range_live(level_no)

    def _validate_range_live(self, level_no: int) -> None:
        company_id = self._company_id()
        range_from, range_to = self._level_widgets[level_no]
        # سطوحِ غیرفعال (فراتر از سقفِ گروه) رنگِ خاکستریِ خودشان (از QSS
        # سراسری) را نگه می‌دارند — رنگِ زنده فقط برایِ سطوحِ قابلِ‌ویرایش است.
        if not range_from.isEnabled():
            range_from.setStyleSheet("")
            range_to.setStyleSheet("")
            return
        if company_id is None or self._selected_type_id is None:
            range_from.setStyleSheet("")
            range_to.setStyleSheet("")
            return
        from_value = range_from.value() or None
        to_value = range_to.value() or None
        if from_value is None and to_value is None:
            range_from.setStyleSheet("")
            range_to.setStyleSheet("")
            return
        conflict = dimensions_service.check_range_conflict(
            company_id, self._selected_type_id, level_no, from_value, to_value, self._selected_person_group_id
        )
        color = theme.DANGER if conflict else theme.SUCCESS
        style = f"border: 2px solid {color};"
        range_from.setStyleSheet(style)
        range_to.setStyleSheet(style)
        range_from.setToolTip(conflict or "")
        range_to.setToolTip(conflict or "")

    def _save_levels(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_type_id is None:
            return
        # اگر «تعدادِ سطح» در UI تغییر کرده ولی دکمه‌ی «ذخیره»یِ خودش کلیک
        # نشده باشد، این دو مقدار (سقفِ نمایش‌داده‌شده در فرم، و سقفِ
        # ذخیره‌شده در دیتابیس) از هم جدا می‌افتند — و چون پایین‌تر فقط
        # سطوحِ «تا همین سقف» ذخیره می‌شوند، بازه‌یِ سطوحِ بالاترِ ذخیره‌شده‌یِ
        # قبلی بی‌سروصدا پاک می‌شد. با ذخیره‌یِ سقف همین‌جا (پیش از فیلترکردن)
        # این دو همیشه هم‌زمان و هماهنگ می‌مانند.
        try:
            dimensions_service.set_group_max_level_no(
                self._selected_type_id, company_id, self.max_level_spin.value(), self._selected_person_group_id
            )
        except ValueError as exc:
            self._show_type_status(str(exc), ok=False)
            return
        except Exception as exc:  # noqa: BLE001 — هیچ خطایی نباید بدونِ پیام به کاربر بی‌صدا بمونه
            self._show_type_status(f"خطایِ غیرمنتظره در ذخیره‌یِ سقفِ سطح: {exc}", ok=False)
            return
        max_level_no = self.max_level_spin.value()
        levels = {
            level_no: {
                "range_from": range_from.value() or None,
                "range_to": range_to.value() or None,
            }
            for level_no, (range_from, range_to) in self._level_widgets.items()
            if level_no <= max_level_no and (range_from.value() > 0 or range_to.value() > 0)
        }
        try:
            dimensions_service.set_group_levels(
                self._selected_type_id, company_id, levels, self._selected_person_group_id
            )
        except ValueError as exc:
            self._show_type_status(str(exc), ok=False)
            return
        except Exception as exc:  # noqa: BLE001
            self._show_type_status(f"خطایِ غیرمنتظره در ذخیره‌یِ بازه‌یِ سطوح: {exc}", ok=False)
            return
        self._show_type_status("تعدادِ سطح و بازه‌یِ سطوح ذخیره شد.", ok=True)
        self._saved_max_level_no = max_level_no
        self._update_level_save_hint()
        for level_no in self._level_widgets:
            self._validate_range_live(level_no)

    def _show_type_status(self, text: str, *, ok: bool) -> None:
        theme.set_status_label(self.type_status_label, text, ok=ok)

    # --- عنوان + حذفِ کاملِ گروه ---------------------------------------------
    def _save_title(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_type_id is None:
            return
        new_title = self.title_field.text().strip()
        if not new_title:
            self._show_type_status("عنوان را وارد کنید.", ok=False)
            return
        try:
            if self._selected_person_group_id:
                dimensions_service.set_person_group_name(self._selected_person_group_id, company_id, new_title)
            else:
                dim_type = next((t for t in self._types if t.dimension_type_id == self._selected_type_id), None)
                if dim_type is None:
                    return
                dimensions_service.update_dimension_type(
                    self._selected_type_id, company_id, new_title, dim_type.is_active
                )
        except ValueError as exc:
            self._show_type_status(str(exc), ok=False)
            return
        self._show_type_status("عنوان ذخیره شد.", ok=True)
        selected_type_id, selected_person_group_id = self._selected_type_id, self._selected_person_group_id
        self.refresh()
        self._select_type(selected_type_id, selected_person_group_id)

    def _on_is_personnel_toggled(self, checked: bool) -> None:
        if not self._selected_person_group_id:
            return
        dimensions_service.set_group_is_personnel(self._selected_person_group_id, checked)
        self._show_type_status("ذخیره شد.", ok=True)

    def _delete_group(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_type_id is None:
            return
        confirm = QMessageBox.question(
            self,
            "حذفِ کاملِ گروه",
            "این گروه به‌همراهِ همه‌یِ حساب‌هایِ تفصیلی/سطوح/فیلدهایِ اختصاصی‌اش حذف شود؟ "
            "الزامِ این گروه رویِ معین‌هایِ کدینگ (اگر بود) هم برداشته می‌شود. این کار قابلِ‌بازگشت نیست.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            dimensions_service.delete_custom_group_completely(self._selected_type_id, company_id)
        except ValueError as exc:
            self._show_type_status(str(exc), ok=False)
            return
        self._selected_type_id = None
        self._selected_person_group_id = 0
        self._show_type_status("گروه کاملاً حذف شد.", ok=True)
        self.refresh()

    # --- رنگِ گروه ---------------------------------------------------------
    def _apply_color_swatch(self, color: str | None) -> None:
        self.color_button.setStyleSheet(
            f"background-color: {color or theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 4px;"
        )

    def _pick_color(self) -> None:
        if self._selected_type_id is None:
            return
        initial = QColor(self._current_color) if self._current_color else QColor(Qt.white)
        color = QColorDialog.getColor(initial, self, "انتخابِ رنگِ گروه")
        if not color.isValid():
            return
        self._save_color(color.name())

    def _clear_color(self) -> None:
        if self._selected_type_id is None:
            return
        self._save_color(None)

    def _save_color(self, color: str | None) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_type_id is None:
            return
        try:
            if self._selected_person_group_id:
                dimensions_service.set_person_group_color(self._selected_person_group_id, company_id, color)
            else:
                dimensions_service.set_dimension_type_color(self._selected_type_id, company_id, color)
        except ValueError as exc:
            self._show_type_status(str(exc), ok=False)
            return
        self._current_color = color
        self._apply_color_swatch(color)
        self._show_type_status("رنگِ گروه ذخیره شد.", ok=True)
        selected_type_id, selected_person_group_id = self._selected_type_id, self._selected_person_group_id
        self.refresh()
        self._select_type(selected_type_id, selected_person_group_id)

    # --- فیلدهایِ اختصاصیِ گروه --------------------------------------------
    def _load_fields(self) -> None:
        while self.fields_container.count():
            child = self.fields_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._field_rows = []
        for field_row in dimensions_service.list_group_fields(self._selected_type_id, self._selected_person_group_id):
            self._add_field_row(field_row)

    def _add_field_row(self, initial: dimensions_service.GroupFieldRow | None = None) -> None:
        row_widget = _GroupFieldRowWidget(self._remove_field_row, initial)
        self.fields_container.addWidget(row_widget)
        self._field_rows.append(row_widget)

    def _remove_field_row(self, row_widget: _GroupFieldRowWidget) -> None:
        self._field_rows.remove(row_widget)
        self.fields_container.removeWidget(row_widget)
        row_widget.deleteLater()

    def _save_fields(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_type_id is None:
            return
        fields = [row.to_field_dict(i) for i, row in enumerate(self._field_rows)]
        for f in fields:
            if not f["field_key"] or not f["label"]:
                self._show_type_status("کلید و عنوانِ همه‌ی فیلدها را پر کنید.", ok=False)
                return
        try:
            dimensions_service.set_group_fields(
                self._selected_type_id, company_id, fields, self._selected_person_group_id
            )
        except ValueError as exc:
            self._show_type_status(str(exc), ok=False)
            return
        except Exception as exc:  # noqa: BLE001
            self._show_type_status(f"خطایِ غیرمنتظره در ذخیره‌یِ فیلدها: {exc}", ok=False)
            return
        self._show_type_status("فیلدها ذخیره شد.", ok=True)
        self._load_fields()
