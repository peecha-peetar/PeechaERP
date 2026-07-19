"""میانبرهای کیبوردِ مشترک بین همه‌ی فرم‌ها.

درخواست صریح کاربر: کارِ فرم‌ها باید بدون ماوس هم ممکن باشد. این ماژول
یک قرارداد مشترک تعریف می‌کند (نه هر صفحه میانبر خودش را جدا پیاده کند):

- Ctrl+S یا Enter (خارج از یک TextInputِ چندخطی): ثبت/ذخیره‌ی فرم
- Delete: حذفِ ردیف/آیتمِ انتخاب‌شده (اگر صفحه پشتیبانی کند)
- Escape: لغو/پاک‌کردنِ فرم یا بستنِ دیالوگ

هر Screen ای که می‌خواهد از این قرارداد استفاده کند، از KeyboardShortcutMixin
ارث می‌برد و متدهای on_shortcut_save/on_shortcut_delete/on_shortcut_cancel
را override می‌کند (پیش‌فرضِ هرکدام کاری نمی‌کند)، و در on_pre_enter/on_leave
خودش bind_shortcuts()/unbind_shortcuts() را صدا می‌زند — عمداً این کار در
on_pre_enter/on_leave خودِ mixin انجام نمی‌شود چون اکثر صفحات همین متدها را
برای کار دیگری override کرده‌اند و ترکیب‌شان با super() شکننده می‌شود.
"""

from __future__ import annotations

from kivy.core.window import Window

_KEY_ESCAPE = 27
_KEY_DELETE = 127
_KEY_S = 115


class KeyboardShortcutMixin:
    def bind_shortcuts(self) -> None:
        Window.bind(on_key_down=self._on_shortcut_key_down)

    def unbind_shortcuts(self) -> None:
        Window.unbind(on_key_down=self._on_shortcut_key_down)

    def _on_shortcut_key_down(self, _window, key: int, _scancode, _codepoint, modifiers: list[str]) -> bool:
        ctrl = "ctrl" in modifiers
        if ctrl and key == _KEY_S:
            self.on_shortcut_save()
            return True
        if key == _KEY_DELETE:
            return bool(self.on_shortcut_delete())
        if key == _KEY_ESCAPE:
            return bool(self.on_shortcut_cancel())
        return False

    def on_shortcut_save(self) -> None:
        """پیش‌فرض کاری نمی‌کند؛ صفحه‌هایی که فرمِ ثبت دارند override می‌کنند."""

    def on_shortcut_delete(self) -> bool:
        """اگر آیتمی برای حذف انتخاب شده True برگرداند (رویداد را مصرف می‌کند)."""
        return False

    def on_shortcut_cancel(self) -> bool:
        """اگر کاری برای لغو/بستن انجام شد True برگرداند."""
        return False
