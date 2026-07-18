"""تنظیمات اتصال به دیتابیس.

اولویت خواندن: متغیرهای محیطی (.env، برای توسعه/CI) > فایل تنظیمات کاربر
(که فرم «تنظیمات اتصال» در UI می‌سازد) > مقادیر پیش‌فرض.

فایل تنظیمات کاربر در پوشه‌ی home کاربر ذخیره می‌شود (نه داخل پوشه‌ی پروژه)
چون در نسخه‌ی نصب‌شده/توزیع‌شده‌ی برنامه، پوشه‌ی پروژه لزوماً قابل‌نوشتن یا
حتی موجود نیست. فعلاً به‌صورت JSON ساده (بدون رمزنگاری) ذخیره می‌شود —
برای نسخه‌ی توسعه کافی است؛ رمزنگاری رمز عبور یک بهبود آتی است.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SETTINGS_DIR = Path(os.environ.get("PEECHA_CONFIG_DIR", Path.home() / ".peecha"))
SETTINGS_FILE = SETTINGS_DIR / "connection.json"

_ENV_KEYS = {
    "host": "PEECHA_DB_HOST",
    "port": "PEECHA_DB_PORT",
    "name": "PEECHA_DB_NAME",
    "user": "PEECHA_DB_USER",
    "password": "PEECHA_DB_PASSWORD",
}

_DEFAULTS = {
    "host": "localhost",
    "port": 5432,
    "name": "peecha",
    "user": "peecha",
    "password": "",
}


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str

    @property
    def sqlalchemy_url(self) -> str:
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


def _read_settings_file() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def has_saved_settings() -> bool:
    """آیا کاربر قبلاً یک‌بار از فرم تنظیمات اتصال ذخیره کرده؟

    برای تصمیم‌گیری اپ که موقع شروع فرم تنظیمات را نشان بدهد یا مستقیم برود
    سراغ صفحه‌ی ورود.
    """
    return SETTINGS_FILE.exists() or any(os.environ.get(v) for v in _ENV_KEYS.values())


def load_database_config() -> DatabaseConfig:
    file_values = _read_settings_file()
    values = {}
    for field, env_key in _ENV_KEYS.items():
        env_value = os.environ.get(env_key)
        if env_value is not None:
            values[field] = env_value
        elif field in file_values:
            values[field] = file_values[field]
        else:
            values[field] = _DEFAULTS[field]
    return DatabaseConfig(
        host=str(values["host"]),
        port=int(values["port"]),
        name=str(values["name"]),
        user=str(values["user"]),
        password=str(values["password"]),
    )


def save_database_config(config: DatabaseConfig) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")


def test_connection(config: DatabaseConfig) -> tuple[bool, str]:
    """اتصال را امتحان می‌کند؛ (موفق؟, پیام) را برمی‌گرداند. اتصال آزمایشی
    را می‌بندد، روی engine اصلی برنامه اثری ندارد."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import SQLAlchemyError

    try:
        engine = create_engine(config.sqlalchemy_url, future=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True, "اتصال موفق بود."
    except SQLAlchemyError as exc:
        return False, str(exc.__cause__ or exc)
