"""رمزنگاریِ اطلاعاتِ حساسِ اتصال به فروشگاهِ اینترنتی (کلیدِ API ووکامرس،
کلیدِ Webserviceِ پرستاشاپ) پیش از ذخیره در ستونِ
comm.marketplace_connections.credentials_encrypted.

کلید یک‌بار تولید و در فایلِ محلیِ ~/.peecha/ecommerce.key نگه‌داری
می‌شود (هم‌الگو با فایلِ تنظیماتِ اتصالِ دیتابیس در config.py) — یا اگر
متغیرِ محیطیِ PEECHA_ECOMMERCE_KEY صریحاً تنظیم شده باشد، همان اولویت
دارد (برایِ استقرارهایِ چندسیستمی که کلید باید مشترک باشد)."""

from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken

from peecha.config import SETTINGS_DIR

_KEY_FILE = SETTINGS_DIR / "ecommerce.key"


def _get_or_create_key() -> bytes:
    env_key = os.environ.get("PEECHA_ECOMMERCE_KEY")
    if env_key:
        return env_key.encode("utf-8")
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    try:
        os.chmod(_KEY_FILE, 0o600)
    except OSError:
        pass
    return key


def encrypt_credentials(data: dict) -> bytes:
    fernet = Fernet(_get_or_create_key())
    return fernet.encrypt(json.dumps(data or {}).encode("utf-8"))


def decrypt_credentials(blob: bytes | None) -> dict:
    if not blob:
        return {}
    fernet = Fernet(_get_or_create_key())
    try:
        return json.loads(fernet.decrypt(bytes(blob)).decode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("اطلاعاتِ اتصالِ رمزنگاری‌شده قابلِ‌بازخوانی نیست -- کلیدِ رمزنگاری تغییر کرده است.") from exc
