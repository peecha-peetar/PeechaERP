"""صفحه‌ی مدیریتِ ابعادِ تفصیلی/مراکزِ هزینه.

پنلِ راست: فهرستِ «نوع‌بُعد»ها (مثلِ مرکزِ هزینه، پروژه، مشتری) — هرکدام
یک ردیف در acc.detail_dimension_types. با انتخابِ یک نوع‌بُعد، پنلِ چپ
حساب‌های تفصیلیِ همان نوع را نشان می‌دهد (acc.detail_accounts) — دقیقاً
همان الگویِ فهرست/فرمِ اصلی‌شده در chart_of_accounts.py/roles.py، فقط
تودرتو (نوع‌بُعد → حساب‌های تفصیلی‌اش)."""

from __future__ import annotations

import os

from kivy.factory import Factory
from kivy.lang import Builder
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import detail_dimensions as dimensions_service
from peecha.ui import numerals, theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin
from peecha.ui.widgets import open_rtl_dropdown

_KV_PATH = os.path.join(os.path.dirname(__file__), "detail_dimensions.kv")
Builder.load_file(_KV_PATH)

_FIELD_KIND_LABELS = {"text": "متن", "decimal": "عدد اعشاری", "date": "تاریخ", "boolean": "بله/خیر"}


class DimensionTypeRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    dimension_type_id = NumericProperty(0)
    code_text = StringProperty("")
    count_text = StringProperty("")
    status_text = StringProperty("")
    is_active_row = BooleanProperty(True)
    zebra = BooleanProperty(False)
    selected = BooleanProperty(False)
    on_edit = ObjectProperty(None)
    on_delete = ObjectProperty(None)

    def on_release(self) -> None:
        if self.on_edit is not None:
            self.on_edit(self.dimension_type_id)

    def request_delete(self) -> None:
        if self.on_delete is not None:
            self.on_delete(self.dimension_type_id)


Factory.register("DimensionTypeRowWidget", cls=DimensionTypeRowWidget)


class DetailAccountRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    detail_account_id = NumericProperty(0)
    code_text = StringProperty("")
    status_text = StringProperty("")
    is_active_row = BooleanProperty(True)
    zebra = BooleanProperty(False)
    selected = BooleanProperty(False)
    on_edit = ObjectProperty(None)
    on_delete = ObjectProperty(None)

    def on_release(self) -> None:
        if self.on_edit is not None:
            self.on_edit(self.detail_account_id)

    def request_delete(self) -> None:
        if self.on_delete is not None:
            self.on_delete(self.detail_account_id)


Factory.register("DetailAccountRowWidget", cls=DetailAccountRowWidget)


class GroupFieldEditRow(MDBoxLayout):
    """یک ردیفِ ویرایشِ فیلدِ اختصاصیِ گروه (کلید/برچسب/نوع/الزامی/حذف) —
    طبقِ درخواستِ صریح: کاربر باید بتواند برایِ گروهِ تازه‌تعریف‌شده (مثلِ
    «بانک») خودش فیلدهای اختصاصی تعریف کند."""

    def __init__(self, on_remove, initial: dimensions_service.GroupFieldRow | None = None, **kwargs):
        super().__init__(**kwargs)
        self._on_remove = on_remove
        self._menu: MDDropdownMenu | None = None
        self.kind = initial.kind if initial else "text"
        self.ids.key_field.text = initial.field_key if initial else ""
        self.ids.label_field.text = initial.label if initial else ""
        self.ids.required_checkbox.active = initial.is_required if initial else False
        self.ids.kind_button.text = shape(_FIELD_KIND_LABELS[self.kind])

    def open_kind_menu(self) -> None:
        items = [
            {"text": shape(label), "on_release": lambda k=kind: self._choose_kind(k)}
            for kind, label in _FIELD_KIND_LABELS.items()
        ]
        self._menu = open_rtl_dropdown(self.ids.kind_button, items, width_mult=3)

    def _choose_kind(self, kind: str) -> None:
        if self._menu is not None:
            self._menu.dismiss()
        self.kind = kind
        self.ids.kind_button.text = shape(_FIELD_KIND_LABELS[kind])

    def remove(self) -> None:
        self._on_remove(self)

    def to_field_dict(self, sort_order: int) -> dict:
        return {
            "field_key": self.ids.key_field.value.strip(),
            "label": self.ids.label_field.value.strip(),
            "kind": self.kind,
            "is_required": self.ids.required_checkbox.active,
            "sort_order": sort_order,
        }


class DetailDimensionsScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._types_by_id: dict[int, dimensions_service.DimensionTypeRow] = {}
        self._editing_type_id: int | None = None
        self._selected_type_id: int | None = None
        self._accounts_by_id: dict[int, dimensions_service.DetailAccountRow] = {}
        self._editing_account_id: int | None = None
        self._delete_dialog: MDDialog | None = None
        self._group_field_rows: list[GroupFieldEditRow] = []
        self._parent_options: list[dimensions_service.DetailAccountRow] = []
        self._selected_parent_id: int | None = None
        self._parent_menu: MDDropdownMenu | None = None

    def on_pre_enter(self, *args):
        self.refresh_types()
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def on_shortcut_save(self) -> None:
        if self._selected_type_id is not None and self.ids.account_code_field.focus:
            self.save_detail_account()
        else:
            self.save_dimension_type()

    def on_shortcut_cancel(self) -> bool:
        if self._editing_account_id is not None:
            self.cancel_account_edit()
            return True
        if self._editing_type_id is not None:
            self.cancel_type_edit()
            return True
        return False

    def _current_company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.status_label.text = shape(message)
        self.ids.status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    def _set_account_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.account_status_label.text = shape(message)
        self.ids.account_status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    def select_type_and_edit(self, dimension_type_id: int, detail_account_id: int) -> None:
        """برایِ کلیک از فهرستِ واحدِ «تفصیلی‌ها»: این گروه را انتخاب و
        مستقیم فرمِ ویرایشِ همین حسابِ تفصیلی را باز می‌کند."""
        self.refresh_types()
        self._select_type(dimension_type_id)
        self.edit_detail_account(detail_account_id)

    # --- نوع‌بُعدها -----------------------------------------------------------

    def refresh_types(self) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."), is_error=True)
            self.ids.types_list.data = []
            return

        rows = dimensions_service.list_dimension_types(company_id)
        self._types_by_id = {r.dimension_type_id: r for r in rows}
        if not rows:
            self.ids.types_list.data = [
                {
                    "viewclass": "PEmptyState",
                    "icon": "shape-outline",
                    "text": shape(tr("هنوز نوع‌بُعدی (مثلاً مرکز هزینه) تعریف نشده است.")),
                }
            ]
        else:
            self.ids.types_list.data = [
                {
                    "dimension_type_id": row.dimension_type_id,
                    "on_edit": self.edit_dimension_type,
                    "on_delete": self.confirm_delete_type,
                    "code_text": row.code,
                    "count_text": str(row.detail_account_count),
                    "status_text": shape(tr("فعال") if row.is_active else tr("غیرفعال")),
                    "is_active_row": row.is_active,
                    "zebra": i % 2 == 1,
                    "selected": row.dimension_type_id == self._editing_type_id,
                }
                for i, row in enumerate(rows)
            ]

        if self._selected_type_id is not None and self._selected_type_id not in self._types_by_id:
            self._select_type(None)
        elif self._selected_type_id is not None:
            self.refresh_accounts()

    def edit_dimension_type(self, dimension_type_id: int) -> None:
        row = self._types_by_id.get(dimension_type_id)
        if row is None:
            return
        self._editing_type_id = dimension_type_id
        self.ids.type_code_field.set_value(row.code)
        self.ids.type_active_checkbox.active = row.is_active
        self.ids.type_form_title.text = shape(tr("ویرایش نوع‌بُعد «{}»").format(row.code))
        self.ids.type_save_button.text = shape(tr("ذخیره تغییرات"))
        self.ids.type_cancel_button.opacity = 1
        self.ids.type_cancel_button.disabled = False
        self.ids.type_cancel_button.size_hint_y = None
        self.ids.type_cancel_button.height = "36dp"
        self._set_status(tr("در حال ویرایش «{}» — Escape برای لغو.").format(row.code))
        self.refresh_types()
        self._select_type(dimension_type_id)

    def cancel_type_edit(self) -> None:
        self._editing_type_id = None
        self.ids.type_code_field.text = ""
        self.ids.type_active_checkbox.active = True
        self.ids.type_form_title.text = shape(tr("افزودنِ نوع‌بُعدِ تازه"))
        self.ids.type_save_button.text = shape(tr("افزودن"))
        self.ids.type_cancel_button.opacity = 0
        self.ids.type_cancel_button.disabled = True
        self.ids.type_cancel_button.size_hint_y = None
        self.ids.type_cancel_button.height = "0dp"
        self._set_status(tr(""))
        self.refresh_types()

    def save_dimension_type(self) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."), is_error=True)
            return

        if self._editing_type_id is not None:
            code = self.ids.type_code_field.value.strip()
            if not code:
                self._set_status(tr("کدِ نوع‌بُعد را وارد کنید."), is_error=True)
                return
            try:
                dimensions_service.update_dimension_type(
                    dimension_type_id=self._editing_type_id,
                    company_id=company_id,
                    code=code,
                    is_active=self.ids.type_active_checkbox.active,
                )
            except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
                self._set_status(tr("خطا: {}").format(exc), is_error=True)
                return
            self.cancel_type_edit()
            return

        code = self.ids.type_code_field.value.strip()
        if not code:
            self._set_status(tr("کدِ نوع‌بُعد را وارد کنید."), is_error=True)
            return
        try:
            dimension_type = dimensions_service.create_dimension_type(company_id=company_id, code=code)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self.ids.type_code_field.text = ""
        self._set_status(f"نوع‌بُعد «{dimension_type.code}» ساخته شد؛ حالا حساب‌های تفصیلیِ آن را اضافه کنید.")
        self.refresh_types()
        self._select_type(dimension_type.dimension_type_id)

    def confirm_delete_type(self, dimension_type_id: int) -> None:
        row = self._types_by_id.get(dimension_type_id)
        if row is None:
            return
        if self._delete_dialog is not None:
            self._delete_dialog.dismiss()

        def _do_delete(*_args) -> None:
            self._delete_dialog.dismiss()
            self._perform_delete_type(dimension_type_id)

        self._delete_dialog = MDDialog(
            title=shape(tr("حذف نوع‌بُعد")),
            text=shape(tr("نوع‌بُعد «{}» حذف شود؟ این کار قابل بازگشت نیست.").format(row.code)),
            buttons=[
                MDFlatButton(text=shape(tr("لغو")), on_release=lambda *_: self._delete_dialog.dismiss()),
                MDRaisedButton(text=shape(tr("حذف")), md_bg_color=theme.DANGER, on_release=_do_delete),
            ],
        )
        self._delete_dialog.open()

    def _perform_delete_type(self, dimension_type_id: int) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            return
        try:
            dimensions_service.delete_dimension_type(dimension_type_id, company_id)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        if self._editing_type_id == dimension_type_id:
            self.cancel_type_edit()
        else:
            self._set_status(tr("نوع‌بُعد حذف شد."))
            self.refresh_types()

    # --- حساب‌های تفصیلیِ نوع‌بُعدِ انتخاب‌شده ----------------------------------

    def _select_type(self, dimension_type_id: int | None) -> None:
        self._selected_type_id = dimension_type_id
        self._editing_account_id = None
        self._reset_account_extra_fields()
        self.ids.account_code_field.text = ""
        self.ids.account_active_checkbox.active = True
        self.ids.account_save_button.text = shape(tr("افزودن"))
        self.ids.account_cancel_button.opacity = 0
        self.ids.account_cancel_button.disabled = True
        self.ids.account_cancel_button.size_hint_y = None
        self.ids.account_cancel_button.height = "0dp"
        self._set_account_status(tr(""))
        if dimension_type_id is None:
            self.ids.accounts_panel.opacity = 0
            self.ids.accounts_panel.disabled = True
            self.ids.accounts_empty_label.opacity = 1
            self.ids.accounts_list.data = []
            self.ids.group_config_panel.opacity = 0
            self.ids.group_config_panel.disabled = True
            return
        row = self._types_by_id.get(dimension_type_id)
        self.ids.accounts_panel.opacity = 1
        self.ids.accounts_panel.disabled = False
        self.ids.accounts_empty_label.opacity = 0
        self.ids.accounts_title.text = shape(tr("حساب‌های تفصیلیِ «{}»").format(row.code if row else ""))
        self.ids.group_config_panel.opacity = 1
        self.ids.group_config_panel.disabled = False
        self._load_group_levels()
        self._load_group_fields()
        self.refresh_accounts()

    # --- پیکربندیِ سطح‌های کد ---------------------------------------------

    def _load_group_levels(self) -> None:
        levels_by_no = {
            level.level_no: level.code_length for level in dimensions_service.list_group_levels(self._selected_type_id)
        }
        for level_no in range(1, dimensions_service.MAX_DETAIL_LEVEL + 1):
            field = self.ids.get(f"level_{level_no}_length_field")
            if field is not None:
                length = levels_by_no.get(level_no)
                field.text = numerals.to_persian_digits(str(length)) if length else ""

    def save_group_levels(self) -> None:
        if self._selected_type_id is None:
            return
        company_id = self._current_company_id()
        if company_id is None:
            return
        levels: dict[int, int] = {}
        for level_no in range(1, dimensions_service.MAX_DETAIL_LEVEL + 1):
            field = self.ids.get(f"level_{level_no}_length_field")
            if field is None:
                continue
            raw = numerals.to_ascii_digits(field.text).strip()
            if raw:
                try:
                    levels[level_no] = int(raw)
                except ValueError:
                    self._set_status(tr("طولِ کدِ سطحِ {} باید عددِ صحیح باشد.").format(level_no), is_error=True)
                    return
        try:
            dimensions_service.set_group_levels(self._selected_type_id, company_id, levels)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self._set_status(tr("پیکربندیِ سطح‌ها ذخیره شد."))

    # --- فیلدهای اختصاصیِ گروه ---------------------------------------------

    def _load_group_fields(self) -> None:
        self.ids.group_fields_box.clear_widgets()
        self._group_field_rows = []
        for row in dimensions_service.list_group_fields(self._selected_type_id):
            self._add_group_field_widget(row)

    def _add_group_field_widget(self, initial: dimensions_service.GroupFieldRow | None = None) -> None:
        widget = GroupFieldEditRow(on_remove=self._remove_group_field_widget, initial=initial)
        self._group_field_rows.append(widget)
        self.ids.group_fields_box.add_widget(widget)

    def add_group_field_row(self) -> None:
        self._add_group_field_widget()

    def _remove_group_field_widget(self, widget: GroupFieldEditRow) -> None:
        if widget in self._group_field_rows:
            self._group_field_rows.remove(widget)
            self.ids.group_fields_box.remove_widget(widget)

    def save_group_fields(self) -> None:
        if self._selected_type_id is None:
            return
        company_id = self._current_company_id()
        if company_id is None:
            return
        fields = [row.to_field_dict(i) for i, row in enumerate(self._group_field_rows)]
        for f in fields:
            if not f["field_key"] or not f["label"]:
                self._set_status(tr("کلید و برچسبِ همه‌ی فیلدها را پر کنید."), is_error=True)
                return
        try:
            dimensions_service.set_group_fields(self._selected_type_id, company_id, fields)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self._set_status(tr("فیلدهای اختصاصی ذخیره شد."))
        self._load_group_fields()

    # --- والد (سلسله‌مراتب) و فیلدهای اختصاصیِ فرمِ حسابِ تفصیلی -----------------

    def _reset_account_extra_fields(self) -> None:
        self._selected_parent_id = None
        self.ids.account_parent_button.text = shape(tr("— بدون والد (سطح ۱) —"))
        self.ids.account_extra_fields_box.clear_widgets()

    def open_parent_menu(self) -> None:
        if self._selected_type_id is None:
            return
        company_id = self._current_company_id()
        if company_id is None:
            return
        all_rows = dimensions_service.list_detail_accounts(company_id, self._selected_type_id)
        # طبقِ درخواستِ صریح (تا ۴ سطح): فقط ردیف‌هایی که هنوز به سقفِ سطح
        # نرسیده‌اند می‌توانند والدِ سطحِ بعدی باشند؛ خودِ ردیفِ درحالِ‌ویرایش
        # هم از فهرست کنار گذاشته می‌شود (نمی‌تواند والدِ خودش باشد).
        self._parent_options = [
            r
            for r in all_rows
            if r.level_no < dimensions_service.MAX_DETAIL_LEVEL and r.detail_account_id != self._editing_account_id
        ]
        items = [
            {
                "text": shape(tr("— بدون والد (سطح ۱) —")),
                "on_release": lambda: self._choose_parent(None, tr("— بدون والد (سطح ۱) —")),
            }
        ] + [
            {
                "text": shape(f"{r.full_code} — {r.name}" if r.name else r.full_code),
                "on_release": lambda pid=r.detail_account_id, label=(f"{r.full_code} — {r.name}" if r.name else r.full_code): self._choose_parent(pid, label),
            }
            for r in self._parent_options
        ]
        self._parent_menu = open_rtl_dropdown(self.ids.account_parent_button, items, width_mult=3)

    def _choose_parent(self, parent_id: int | None, label: str) -> None:
        if self._parent_menu is not None:
            self._parent_menu.dismiss()
        self._selected_parent_id = parent_id
        self.ids.account_parent_button.text = shape(label)

    def _render_account_extra_fields(self, values: dict | None = None) -> None:
        self.ids.account_extra_fields_box.clear_widgets()
        if self._selected_type_id is None:
            return
        values = values or {}
        for field_def in dimensions_service.list_group_fields(self._selected_type_id):
            row = MDBoxLayout(orientation="vertical", size_hint_y=None, height="52dp", spacing="2dp")
            row.add_widget(
                Factory.PLabel(
                    text=shape(field_def.label), font_style="Caption", size_hint_y=None, height="18dp", valign="middle"
                )
            )
            if field_def.kind == "boolean":
                check_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height="28dp", spacing="8dp")
                checkbox = Factory.MDCheckbox(
                    active=bool(values.get(field_def.field_key, False)), size_hint=(None, None), size=("24dp", "24dp")
                )
                check_row.add_widget(checkbox)
                row.add_widget(check_row)
                row.extra_field_widget = checkbox
                row.extra_field_kind = "boolean"
            else:
                text_field = Factory.PTextField()
                text_field.set_value(str(values.get(field_def.field_key) or ""))
                row.add_widget(text_field)
                row.extra_field_widget = text_field
                row.extra_field_kind = field_def.kind
            row.field_key = field_def.field_key
            self.ids.account_extra_fields_box.add_widget(row)

    def _collect_account_extra_fields(self) -> dict:
        result: dict[str, object] = {}
        for row in self.ids.account_extra_fields_box.children:
            key = getattr(row, "field_key", None)
            if key is None:
                continue
            widget = row.extra_field_widget
            if row.extra_field_kind == "boolean":
                result[key] = widget.active
            else:
                result[key] = widget.value.strip()
        return result

    def refresh_accounts(self) -> None:
        company_id = self._current_company_id()
        if company_id is None or self._selected_type_id is None:
            self.ids.accounts_list.data = []
            return
        rows = dimensions_service.list_detail_accounts(company_id, self._selected_type_id)
        self._accounts_by_id = {r.detail_account_id: r for r in rows}
        if not rows:
            self.ids.accounts_list.data = [
                {
                    "viewclass": "PEmptyState",
                    "icon": "shape-plus-outline",
                    "text": shape(tr("هنوز حسابِ تفصیلی‌ای برای این نوع‌بُعد تعریف نشده است.")),
                }
            ]
        else:
            self.ids.accounts_list.data = [
                {
                    "detail_account_id": row.detail_account_id,
                    "on_edit": self.edit_detail_account,
                    "on_delete": self.confirm_delete_account,
                    "code_text": row.code,
                    "status_text": shape(tr("فعال") if row.is_active else tr("غیرفعال")),
                    "is_active_row": row.is_active,
                    "zebra": i % 2 == 1,
                    "selected": row.detail_account_id == self._editing_account_id,
                }
                for i, row in enumerate(rows)
            ]
        if self._editing_account_id is not None and self._editing_account_id not in self._accounts_by_id:
            self.cancel_account_edit()

    def edit_detail_account(self, detail_account_id: int) -> None:
        row = self._accounts_by_id.get(detail_account_id)
        if row is None:
            return
        self._editing_account_id = detail_account_id
        self.ids.account_code_field.set_value(row.code)
        self.ids.account_active_checkbox.active = row.is_active
        self.ids.account_save_button.text = shape(tr("ذخیره تغییرات"))
        self.ids.account_cancel_button.opacity = 1
        self.ids.account_cancel_button.disabled = False
        self.ids.account_cancel_button.size_hint_y = None
        self.ids.account_cancel_button.height = "36dp"
        self._set_account_status(tr("در حال ویرایش «{}» — Escape برای لغو.").format(row.code))
        self._selected_parent_id = row.parent_detail_account_id
        if row.parent_detail_account_id is not None:
            parent_row = self._accounts_by_id.get(row.parent_detail_account_id)
            label = (
                f"{parent_row.full_code} — {parent_row.name}" if parent_row and parent_row.name else (parent_row.full_code if parent_row else "")
            )
            self.ids.account_parent_button.text = shape(label)
        else:
            self.ids.account_parent_button.text = shape(tr("— بدون والد (سطح ۱) —"))
        self._render_account_extra_fields(row.extra_fields)
        self.refresh_accounts()

    def cancel_account_edit(self) -> None:
        self._editing_account_id = None
        self.ids.account_code_field.text = ""
        self.ids.account_active_checkbox.active = True
        self.ids.account_save_button.text = shape(tr("افزودن"))
        self.ids.account_cancel_button.opacity = 0
        self.ids.account_cancel_button.disabled = True
        self.ids.account_cancel_button.size_hint_y = None
        self.ids.account_cancel_button.height = "0dp"
        self._set_account_status(tr(""))
        self._selected_parent_id = None
        self.ids.account_parent_button.text = shape(tr("— بدون والد (سطح ۱) —"))
        self._render_account_extra_fields()
        self.refresh_accounts()

    def save_detail_account(self) -> None:
        company_id = self._current_company_id()
        if company_id is None or self._selected_type_id is None:
            self._set_account_status(tr("ابتدا یک نوع‌بُعد را انتخاب کنید."), is_error=True)
            return

        code = self.ids.account_code_field.value.strip()
        if not code:
            self._set_account_status(tr("کدِ حسابِ تفصیلی را وارد کنید."), is_error=True)
            return
        extra_fields = self._collect_account_extra_fields()

        if self._editing_account_id is not None:
            try:
                dimensions_service.update_detail_account(
                    detail_account_id=self._editing_account_id,
                    company_id=company_id,
                    code=code,
                    is_active=self.ids.account_active_checkbox.active,
                    extra_fields=extra_fields,
                )
            except Exception as exc:  # noqa: BLE001
                self._set_account_status(tr("خطا: {}").format(exc), is_error=True)
                return
            self.cancel_account_edit()
            self.refresh_types()
            return

        try:
            dimensions_service.create_detail_account(
                company_id=company_id,
                dimension_type_id=self._selected_type_id,
                code=code,
                parent_detail_account_id=self._selected_parent_id,
                extra_fields=extra_fields,
            )
        except Exception as exc:  # noqa: BLE001
            self._set_account_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self.ids.account_code_field.text = ""
        self._render_account_extra_fields()
        self._set_account_status(tr("حسابِ تفصیلی افزوده شد."))
        self.refresh_accounts()
        self.refresh_types()

    def confirm_delete_account(self, detail_account_id: int) -> None:
        row = self._accounts_by_id.get(detail_account_id)
        if row is None:
            return
        if self._delete_dialog is not None:
            self._delete_dialog.dismiss()

        def _do_delete(*_args) -> None:
            self._delete_dialog.dismiss()
            self._perform_delete_account(detail_account_id)

        self._delete_dialog = MDDialog(
            title=shape(tr("حذف حسابِ تفصیلی")),
            text=shape(tr("حسابِ تفصیلیِ «{}» حذف شود؟ این کار قابل بازگشت نیست.").format(row.code)),
            buttons=[
                MDFlatButton(text=shape(tr("لغو")), on_release=lambda *_: self._delete_dialog.dismiss()),
                MDRaisedButton(text=shape(tr("حذف")), md_bg_color=theme.DANGER, on_release=_do_delete),
            ],
        )
        self._delete_dialog.open()

    def _perform_delete_account(self, detail_account_id: int) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            return
        try:
            dimensions_service.delete_detail_account(detail_account_id, company_id)
        except Exception as exc:  # noqa: BLE001
            self._set_account_status(tr("خطا: {}").format(exc), is_error=True)
            return
        if self._editing_account_id == detail_account_id:
            self.cancel_account_edit()
        else:
            self._set_account_status(tr("حسابِ تفصیلی حذف شد."))
            self.refresh_accounts()
        self.refresh_types()
