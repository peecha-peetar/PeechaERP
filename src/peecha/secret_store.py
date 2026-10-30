"""R378: نگه‌داشتن رمز اتصال پایگاه داده در انبار امن سیستم‌عامل به‌جای متن ساده در connection.json.

- ویندوز: Data Protection API (DPAPI) با کلید حساب کاربری ویندوز؛ فقط همان کاربر روی همان رایانه رمز را باز می‌کند.
  بدون کتابخانهٔ اضافه (ctypes).
- سیستم‌عامل دیگر: اگر کتابخانهٔ keyring نصب باشد از آن، وگرنه رمز مثل قبل در فایل می‌ماند ولی دسترسی فایل فقط برای صاحب آن
  (0600) گذاشته می‌شود.
- اگر رمز محافظت‌شده باز نشود (کاربر یا رایانهٔ دیگر)، رمز خالی برمی‌گردد تا فرم تنظیمات اتصال آن را دوباره بپرسد.
"""

from __future__ import annotations

import base64
import sys

KEYRING_SERVICE = "peecha-erp-database"


class Protector:
    """رابط هر روش نگهداری؛ name در فایل تنظیمات ذخیره می‌شود."""

    name = "plain"

    def protect(self, secret: str, account: str) -> str | None:
        return None

    def unprotect(self, token: str, account: str) -> str | None:
        return None


class _DpapiProtector(Protector):
    name = "dpapi"

    @staticmethod
    def _call(data: bytes, encrypt: bool) -> bytes:
        import ctypes
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        source = ctypes.create_string_buffer(data, len(data))
        blob_in, blob_out = Blob(len(data), source), Blob()
        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
        fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
        description = ctypes.c_wchar_p("Peecha ERP") if encrypt else None
        ok = fn(ctypes.byref(blob_in), description, None, None, None, 0x01, ctypes.byref(blob_out))  # CRYPTPROTECT_UI_FORBIDDEN
        if not ok:
            raise OSError("DPAPI")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)

    def protect(self, secret: str, account: str) -> str | None:
        return base64.b64encode(self._call(secret.encode("utf-8"), True)).decode("ascii")

    def unprotect(self, token: str, account: str) -> str | None:
        return self._call(base64.b64decode(token), False).decode("utf-8")


class _KeyringProtector(Protector):
    name = "keyring"

    def protect(self, secret: str, account: str) -> str | None:
        import keyring

        keyring.set_password(KEYRING_SERVICE, account, secret)
        return account

    def unprotect(self, token: str, account: str) -> str | None:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, token)


def _keyring_available() -> bool:
    try:
        import keyring  # noqa: F401
    except ImportError:
        return False
    return True


_override: Protector | None = None


def use(protector: Protector | None) -> None:
    """برای آزمون: روش نگهداری را جایگزین می‌کند (None = انتخاب خودکار)."""
    global _override
    _override = protector


def current() -> Protector:
    if _override is not None:
        return _override
    if sys.platform == "win32":
        return _DpapiProtector()
    if _keyring_available():
        return _KeyringProtector()
    return Protector()


def by_name(name: str) -> Protector | None:
    if _override is not None and _override.name == name:
        return _override
    return {"dpapi": _DpapiProtector, "keyring": _KeyringProtector}.get(name, lambda: None)()


def protect(secret: str, account: str) -> tuple[str, str] | None:
    """(نام روش، نشانه) یا None اگر روش امنی در دسترس نیست یا شکست خورد."""
    if not secret:
        return None
    protector = current()
    try:
        token = protector.protect(secret, account)
    except Exception:  # noqa: BLE001 -- انبار امن در دسترس نبود؛ رمز مثل قبل در فایل می‌ماند
        return None
    return (protector.name, token) if token else None


def unprotect(name: str, token: str, account: str) -> str | None:
    protector = by_name(name)
    if protector is None:
        return None
    try:
        return protector.unprotect(token, account)
    except Exception:  # noqa: BLE001 -- کاربر یا رایانهٔ دیگر؛ فرم اتصال رمز را دوباره می‌پرسد
        return None
