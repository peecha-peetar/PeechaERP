"""R316: اعداد فارسی در همهٔ برنامه — اسپین‌باکس، جدول و فیلد عددی.

فقط نمایش عوض می‌شود: value() اسپین‌باکس، متن خانهٔ جدول (item.text()) و
مقدار فیلد عددی همان قبلی می‌ماند، پس منطق برنامه دست نمی‌خورد."""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QLocale, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QLineEdit,
    QSpinBox,
    QStyledItemDelegate,
)

from peecha import numerals

PERSIAN_LOCALE = QLocale(QLocale.Persian, QLocale.Iran)
# بازهٔ بزرگ‌تر از این یعنی مبلغ/مقدار است، نه سال یا کد کوتاه
_GROUP_MIN = 100000
_SEPARATORS = ",٬"
_TO_PERSIAN = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_BODY = re.compile(r"^([-−+]?)([\d,٬]*)(?:([.٫])(\d*))?$")
_LATIN = re.compile(r"[A-Za-z]")
_ASCII_DIGIT = re.compile(r"[0-9]")
_NUMERIC_CELL = re.compile(r"^\s*([-−+]?)(\d[\d,٬]*)(?:[.٫](\d+))?\s*([%٪]?)\s*$")
_AMOUNT_HEADERS = ("مبلغ", "مانده", "بدهکار", "بستانکار", "جمع", "قیمت", "بها", "حقوق", "دستمزد", "سقف", "ارزش",
                   "هزینه", "درآمد", "کارمزد", "مقدار", "تعداد", "موجودی", "اعتبار")


def _group_digits(digits: str, sep: str) -> str:
    digits = digits.lstrip("0") or ("0" if digits else "")
    head = len(digits) % 3 or 3
    parts = [digits[:head]] + [digits[i:i + 3] for i in range(head, len(digits), 3)]
    return sep.join(p for p in parts if p)


def group_text(text: str, sep: str = ",", point: str = ".") -> str | None:
    """متن عددی با ارقام فارسی و جداکنندهٔ سه‌رقمی؛ اگر عدد نباشد None."""
    body = (text or "").strip()
    m = _BODY.match(body)
    if not m or not body:
        return None
    sign, whole, dot, frac = m.groups()
    whole = numerals.to_ascii_digits("".join(ch for ch in whole if ch not in _SEPARATORS))
    grouped = _group_digits(whole, sep) if whole else ""
    out = ("-" if sign in "-−" and sign else "") + grouped
    if dot:
        out += point + numerals.to_ascii_digits(frac or "")
    return out.translate(_TO_PERSIAN)


def plain_text(text: str) -> str:
    """متن فیلد بدون جداکننده و با ممیز «.» — همان شکلی که پیش از R316 خوانده می‌شد."""
    text = "".join(ch for ch in (text or "") if ch not in _SEPARATORS)
    return text.replace("٫", ".").replace("−", "-")


def _cursor_after_digits(text: str, count: int, start: int = 0) -> int:
    if count <= 0:
        pos = start
        while pos < len(text) and text[pos] in "-−+":
            pos += 1
        return pos
    seen = 0
    for i in range(start, len(text)):
        if text[i].isdigit():
            seen += 1
            if seen == count:
                return i + 1
    return len(text)


class NumberEdit(QLineEdit):
    """فیلد عددی با ارقام فارسی و سه‌رقم‌سه‌رقم زنده هنگام تایپ.
    text() جداکننده ندارد تا خواننده‌های قبلی (dec، int) بی‌تغییر کار کنند."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.textEdited.connect(self._regroup)

    def text(self) -> str:  # noqa: D102
        return plain_text(super().text())

    def setText(self, text) -> None:  # noqa: N802 — نام متد Qt
        text = "" if text is None else str(text)
        super().setText(group_text(text) or text)

    def keyPressEvent(self, event) -> None:  # noqa: N802 — نام متد Qt
        shown, pos = super().text(), self.cursorPosition()
        if not self.hasSelectedText():
            if event.key() == Qt.Key_Backspace and pos > 0 and shown[pos - 1] in _SEPARATORS:
                self.setCursorPosition(pos - 1)
            elif event.key() == Qt.Key_Delete and pos < len(shown) and shown[pos] in _SEPARATORS:
                self.setCursorPosition(pos + 1)
        if event.text() == "٫":
            event = QKeyEvent(event.type(), event.key(), event.modifiers(), ".")
        super().keyPressEvent(event)

    def _regroup(self, _text: str = "") -> None:
        shown, pos = super().text(), self.cursorPosition()
        grouped = group_text(shown)
        if grouped is None or grouped == shown:
            return
        digits_before = sum(1 for ch in shown[:pos] if ch.isdigit())
        super().setText(grouped)
        self.setCursorPosition(_cursor_after_digits(grouped, digits_before))


def _spin_localizable(spin) -> bool:
    if not isinstance(spin, (QSpinBox, QDoubleSpinBox)) or spin.property("latin_digits"):
        return False
    base = QDoubleSpinBox if isinstance(spin, QDoubleSpinBox) else QSpinBox
    # اسپین‌باکس‌هایی که خودشان متن را می‌سازند (مثل ZeroPaddedSpinBox) دست نمی‌خورند
    return type(spin).textFromValue is base.textFromValue


def _update_grouping(spin) -> None:
    big = max(abs(spin.maximum()), abs(spin.minimum())) >= _GROUP_MIN
    if big and not spin.isGroupSeparatorShown():
        spin.setGroupSeparatorShown(True)


def _regroup_spin(spin) -> None:
    if not spin.isGroupSeparatorShown():
        return
    edit = spin.lineEdit()
    shown, pos = edit.text(), edit.cursorPosition()
    prefix, suffix = spin.prefix(), spin.suffix()
    if not shown.startswith(prefix) or (suffix and not shown.endswith(suffix)):
        return
    body = shown[len(prefix): len(shown) - len(suffix)]
    grouped = group_text(body, "٬", "٫")
    if grouped is None or grouped == body:
        return
    digits_before = sum(1 for ch in shown[:pos] if ch.isdigit())
    text = prefix + grouped + suffix
    edit.setText(text)
    edit.setCursorPosition(_cursor_after_digits(text, digits_before, len(prefix)))


class _SpinKeys(QObject):
    """ارقام لاتین و «.» را به رقم فارسی و «٫» تبدیل می‌کند؛ جعبهٔ فارسی رقم لاتین ممیزدار را نمی‌پذیرد."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — نام متد Qt
        etype = event.type()
        if etype == QEvent.KeyPress:
            text = event.text()
            if text and text in "0123456789." and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
                if text == "." and not isinstance(obj, QDoubleSpinBox):
                    return False
                new_text = "٫" if text == "." else text.translate(_TO_PERSIAN)
                obj.event(QKeyEvent(QEvent.KeyPress, event.key(), event.modifiers(), new_text,
                                    event.isAutoRepeat(), event.count()))
                return True
        elif etype in (QEvent.FocusIn, QEvent.Show):
            _update_grouping(obj)
        return False


_SPIN_KEYS = _SpinKeys()


def localize_spinbox(spin) -> None:
    if spin.property("fa_digits") or not _spin_localizable(spin):
        return
    spin.setProperty("fa_digits", True)
    spin.setLocale(PERSIAN_LOCALE)
    _update_grouping(spin)
    spin.installEventFilter(_SPIN_KEYS)
    spin.lineEdit().textEdited.connect(lambda _t, s=spin: _regroup_spin(s))


def display_text(text: str, amount: bool = False) -> str | None:
    """متن خانهٔ جدول برای نمایش: ارقام فارسی، بدون صفرهای اضافهٔ اعشار، و
    در ستون مبلغ/مقدار سه‌رقم‌سه‌رقم. متنی که حرف لاتین دارد (کد، ایمیل) دست نمی‌خورد."""
    if not text or _LATIN.search(text):
        return None
    m = _NUMERIC_CELL.match(text)
    if not m:
        return text.translate(_TO_PERSIAN) if _ASCII_DIGIT.search(text) else None
    sign, whole, frac, percent = m.groups()
    if frac and len(frac) > 2:
        frac = frac.rstrip("0").rstrip("۰")
    digits = numerals.to_ascii_digits(whole)
    if amount and not any(ch in _SEPARATORS for ch in whole) and len(digits.lstrip("0")) > 3:
        whole = _group_digits(digits, ",")
    out = ("-" if sign in "-−" and sign else sign) + whole + ("." + frac if frac else "") + percent
    out = out.translate(_TO_PERSIAN)
    return out if out != text else None


class PersianDigitsDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index) -> None:  # noqa: N802 — نام متد Qt
        super().initStyleOption(option, index)
        if not option.text:
            return
        header = index.model().headerData(index.column(), Qt.Horizontal, Qt.DisplayRole) if index.model() else None
        amount = isinstance(header, str) and any(word in header for word in _AMOUNT_HEADERS)
        shown = display_text(option.text, amount)
        if shown is not None:
            option.text = shown


def localize_view(view) -> None:
    if view.property("fa_digits") or view.property("latin_digits"):
        return
    view.setProperty("fa_digits", True)
    if type(view.itemDelegate()) is QStyledItemDelegate:
        view.setItemDelegate(PersianDigitsDelegate(view))
