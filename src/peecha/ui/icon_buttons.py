"""R316: دکمه‌های متنی باقی‌مانده ← دکمهٔ آیکونی با تول‌تیپ، در همهٔ برنامه.

همان شکل module_style.style_button: آیکن روی دکمه، برچسب در تول‌تیپ و accessibleName.
فقط ظاهر عوض می‌شود؛ سیگنال و کار دکمه همان است."""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QDialogButtonBox, QMessageBox, QPushButton

from peecha.ui.screens import module_style as ms

# (واژه در برچسب، آیکن، نوع) — اولین مورد منطبق به‌کار می‌رود، پس عبارت‌های خاص‌تر بالاترند
_KEYWORDS: list[tuple[str, str, str]] = [
    ("گزارش حرفه‌ای", "📑", ""), ("خروجی PDF", "📄", ""), ("PDF", "📄", ""), ("خروجی Excel", "📊", ""),
    ("خروجی اکسل", "📊", ""), ("ورود از اکسل", "📥", ""), ("ورود صورت‌حساب", "📥", ""), ("CSV", "🧾", ""),
    ("ستون‌ها", "📐", ""), ("کپی", "📋", ""), ("چاپ", "🖨️", ""), ("ذخیرهٔ نما", "📌", ""), ("حذف نما", "🗑️", "danger"),
    ("نمودار", "📈", ""), ("نمایش روی نقشه", "🗺️", ""), ("نمایش مسیر", "🗺️", ""), ("انتخاب روی نقشه", "🗺️", ""),
    ("کل نقشه", "🗺️", ""), ("بازگشت به فهرست", "↩️", ""),
    ("انتخاب همه", "☑️", ""), ("علامت‌خورده", "☑️", "primary"), ("لغو انتخاب", "⬜", ""), ("پاک‌کردن انتخاب", "⬜", ""),
    ("پاک‌کردن", "🧹", "danger"), ("غیرفعال", "🚫", "danger"),
    ("حذف", "🗑️", "danger"), ("جداکردن", "✂️", "danger"), ("لغو", "🚫", "danger"), ("بستن", "🔒", ""),
    ("بازگشایی", "🔓", ""), ("ویرایش", "✏️", ""), ("ذخیره", "💾", "primary"),
    ("به‌روزرسانی", "🔄", ""), ("بروزرسانی", "🔄", ""), ("بازآوری", "🔄", ""), ("بازخوانی", "🔄", ""),
    ("همگام‌سازی", "🔄", ""), ("بارگذاری تطبیق", "🔄", ""), ("دریافت خودکار", "🌐", ""),
    ("بک‌آپ", "📦", ""), ("بازیابی", "📥", ""),
    ("بارگذاری", "📤", ""), ("الصاق", "📎", ""), ("انتخاب لوگو", "🖼️", ""), ("انتخاب عکس", "🖼️", ""),
    ("تایید", "✅", "primary"), ("نهایی", "🏁", "primary"), ("تکمیل", "🏁", ""), ("شروع", "▶️", ""),
    ("پیشنهاد", "💡", ""), ("مسیر جمع‌آوری کالا", "🧭", ""), ("ردیابی", "🧭", ""), ("وظایف", "📋", ""),
    ("شمارش", "🔢", ""), ("وضعیت", "🚦", ""), ("انتقال", "🚚", ""), ("تحویل", "🚚", ""), ("خودرو", "🚚", ""),
    ("برچسب", "🏷️", ""), ("ابعاد", "📏", ""), ("حداقل/حداکثر", "📉", ""), ("مکان پیش‌فرض", "📍", ""),
    ("یافتن", "🔍", "primary"), ("جستجو", "🔍", ""), ("بررسی", "🔍", ""), ("نمایش", "👁️", ""),
    ("استعلام", "📨", ""), ("دعوت", "✉️", ""), ("انصراف", "🙅", ""), ("بهترین پیشنهاد", "🏆", ""),
    ("پیشنهاد", "💬", ""), ("قیمت", "💲", ""), ("اصلی", "⭐", ""), ("پرداخت", "💳", ""), ("وصول", "💰", ""),
    ("تسویه", "🔗", "primary"), ("اختصاص", "🔗", ""), ("نقش‌های آماده", "🛡️", ""), ("کمپین", "📣", "primary"),
    ("موج", "🌊", "primary"), ("جمع‌آوری گروهی", "🌊", "primary"), ("سفارش خرید", "🛒", "primary"), ("صدور", "📤", "primary"), ("ایجاد", "➕", "primary"),
    ("ساخت", "➕", "primary"), ("افزودن", "➕", ""), ("جدید", "➕", "primary"), ("تازه", "➕", ""), ("ثبت", "📌", "primary"),
    ("گزارش", "📊", ""), ("شرایط نگهداری", "💾", ""),
]
_LEADING_GLYPH = re.compile(r"^([^\w\s؀-ۿ]+)\s*(.+)$")
_BOX_ROLES = {
    QDialogButtonBox.AcceptRole: ("✅", "primary"), QDialogButtonBox.YesRole: ("✅", "primary"),
    QDialogButtonBox.ApplyRole: ("💾", "primary"), QDialogButtonBox.RejectRole: ("✖️", ""),
    QDialogButtonBox.NoRole: ("✖️", ""), QDialogButtonBox.DestructiveRole: ("🗑️", "danger"),
    QDialogButtonBox.ResetRole: ("↺", ""), QDialogButtonBox.HelpRole: ("❔", ""),
}
_NAV_CLASSES = ("_SidebarButton", "_QuickAccessTile", "HoverButton", "_StepButton")
# R322: دکمه‌های استاندارد پنجره‌ها (حتی «OK» دوحرفی و دکمه‌های پیام) آیکونی با برچسب فارسی
_STANDARD_LABELS = {
    QDialogButtonBox.Ok: "تایید", QDialogButtonBox.Cancel: "انصراف", QDialogButtonBox.Yes: "بله", QDialogButtonBox.No: "خیر",
    QDialogButtonBox.Save: "ذخیره", QDialogButtonBox.Close: "بستن", QDialogButtonBox.Apply: "اعمال",
    QDialogButtonBox.Discard: "ذخیره نشود", QDialogButtonBox.Abort: "توقف", QDialogButtonBox.Retry: "تلاش دوباره",
    QDialogButtonBox.Ignore: "نادیده گرفتن", QDialogButtonBox.Reset: "بازنشانی", QDialogButtonBox.Help: "راهنما",
    QDialogButtonBox.YesToAll: "بله برای همه", QDialogButtonBox.NoToAll: "خیر برای همه",
    QDialogButtonBox.RestoreDefaults: "بازگشت به پیش‌فرض",
}


def _kind_of(label: str) -> str:
    for word, _glyph, kind in _KEYWORDS:
        if word in label:
            return kind
    return ""


def icon_for(label: str, box_role=None) -> tuple[str, str, str] | None:
    """(آیکن، نوع، برچسب) برای متن دکمه؛ None یعنی دست نخورد."""
    label = (label or "").replace("&", "").strip()
    if len(label) <= 2:
        return None
    if label in ms.ICONS:
        glyph, kind = ms.ICONS[label]
        return glyph, kind, label
    m = _LEADING_GLYPH.match(label)
    if m and not m.group(1).strip().isdigit():
        rest = m.group(2).strip()
        return m.group(1).strip(), _kind_of(rest), rest
    if box_role in _BOX_ROLES:
        glyph, kind = _BOX_ROLES[box_role]
        return glyph, kind, label
    for word, glyph, kind in _KEYWORDS:
        if word in label:
            return glyph, kind, label
    return None


def _box_button(button: QPushButton) -> tuple[str, str, str] | None:
    """دکمهٔ داخل QDialogButtonBox یا پیام: (آیکن، نوع، برچسب فارسی) بر اساس نقش دکمه."""
    box = button.parentWidget()
    if not isinstance(box, QDialogButtonBox):
        return None
    role = box.buttonRole(button)
    if role not in _BOX_ROLES:
        return None
    glyph, kind = _BOX_ROLES[role]
    label = _STANDARD_LABELS.get(box.standardButton(button)) or (button.text() or "").replace("&", "").strip()
    return (glyph, kind, label) if label else None


def _skip(button: QPushButton) -> bool:
    if button.property("keep_text") or button.property("label") or type(button).__name__ in _NAV_CLASSES:
        return True
    if button.isCheckable() and button.autoExclusive():
        return True
    text = button.text().strip()
    # دکمه‌های مرحله («۱ اطلاعات سند») مثل تب‌اند
    if text[:1].isdigit():
        return True
    p = button.parentWidget()
    while p is not None:
        if isinstance(p, QMessageBox) or p.property("keep_text"):
            return True
        p = p.parentWidget()
    return False


def _repolish(button: QPushButton) -> None:
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    button.update()


def iconize(button: QPushButton) -> bool:
    boxed = None if button.property("keep_text") or button.property("label") else _box_button(button)
    if boxed is None and _skip(button):
        return False
    box = button.parentWidget()
    role = box.buttonRole(button) if isinstance(box, QDialogButtonBox) else None
    found = boxed or icon_for(button.text(), role)
    if found is None:
        return False
    _apply(button, *found)
    return True


def _apply(button: QPushButton, glyph: str, kind: str, label: str) -> None:
    # کلید F2 اولین دکمهٔ «اصلی» را می‌زند؛ پس مجموعهٔ دکمه‌های اصلی همان قبلی می‌ماند (دکمهٔ حذف هرگز اصلی نیست)
    was_primary = button.objectName() in ("primaryButton", "primaryIconButton")
    if kind != "danger":
        kind = "primary" if was_primary else ""
    extra = button.toolTip()
    button.setText(glyph)
    button.setToolTip(label + (f" — {extra}" if extra and extra != label else ""))
    button.setAccessibleName(label)
    button.setProperty("label", label)
    button.setObjectName(ms._OBJECT_NAMES[kind])
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    # نام شیء عوض شد؛ استایل‌شیت باید دوباره خوانده شود (بیرون از polish جاری؛ با حذف دکمه لغو می‌شود)
    _Repolisher(button)


def retext(button: QPushButton) -> bool:
    """R336: متن دکمه پس از آیکونی‌شدن دوباره نوشته شده (مثل «ذخیره» یا «تبدیل» روی دکمهٔ تایید پنجره):
    همان متن تول‌تیپ می‌شود و دکمه آیکونی می‌ماند."""
    text = (button.text() or "").replace("&", "").strip()
    if len(text) <= 2 or button.property("keep_text") or type(button).__name__ in _NAV_CLASSES or text[:1].isdigit() \
            or (button.isCheckable() and button.autoExclusive()):
        return False
    box = button.parentWidget()
    role = box.buttonRole(button) if isinstance(box, QDialogButtonBox) else None
    found = icon_for(text, role)
    if found is None and role in _BOX_ROLES:
        found = (*_BOX_ROLES[role], text)
    if found is None:
        return False
    button.setToolTip("")
    _apply(button, *found)
    return True


class _TextWatcher(QObject):
    """هنگام نمایش، دکمهٔ آیکونی‌شده‌ای که متنش دوباره نوشته شده را دوباره آیکونی می‌کند."""

    def eventFilter(self, obj, event):  # noqa: N802 — نام متد Qt
        if event.type() == QEvent.Show and isinstance(obj, QPushButton) and obj.property("label") \
                and len((obj.text() or "").strip()) > 2:
            retext(obj)
        return False


WATCHER = _TextWatcher()


class _Repolisher(QObject):
    def __init__(self, button: QPushButton) -> None:
        super().__init__(button)
        QTimer.singleShot(0, self, self.run)

    def run(self) -> None:
        button = self.parent()
        if button is not None:
            _repolish(button)
        self.deleteLater()
