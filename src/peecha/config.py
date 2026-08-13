"""تنظیمات اتصال به دیتابیس.

اولویت خواندن (به‌ازایِ هر فیلد جداگانه): فایلِ تنظیماتِ کاربر (که فرمِ
«تنظیماتِ اتصال» در UI می‌سازد) > متغیرهایِ محیطی (.env، فقط برایِ
توسعه/CI پیش از اولین ذخیره‌یِ کاربر) > مقادیرِ پیش‌فرض. به‌محضِ اینکه
کاربر یک‌بار از فرم ذخیره کند، دیگر هیچ متغیرِ محیطی‌ای نمی‌تواند آن
تنظیمات را نادیده بگیرد.

فایل تنظیمات کاربر در پوشه‌ی home کاربر ذخیره می‌شود (نه داخل پوشه‌ی پروژه)
چون در نسخه‌ی نصب‌شده/توزیع‌شده‌ی برنامه، پوشه‌ی پروژه لزوماً قابل‌نوشتن یا
حتی موجود نیست. فعلاً به‌صورت JSON ساده (بدون رمزنگاری) ذخیره می‌شود —
برای نسخه‌ی توسعه کافی است؛ رمزنگاری رمز عبور یک بهبود آتی است.
"""

from __future__ import annotations

import json
import os
import re
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
    """اولویتِ واقعی: تنظیماتِ ذخیره‌شده‌یِ کاربر (از فرمِ UI) > متغیرهایِ
    محیطی > مقادیرِ پیش‌فرض.

    قبلاً متغیرهایِ محیطی/`.env` همیشه در اولویتِ اول بودند («برایِ
    توسعه/CI») — یعنی اگر به هر دلیلی (باقی‌ماندهٔ یک `.env` قدیمی، یک
    متغیرِ محیطیِ ویندوزیِ فراموش‌شده) این مقادیر روی سیستمِ کاربرِ نهایی
    ست شده باشند، هیچ‌چیزی که در فرمِ «تنظیماتِ اتصال به دیتابیس» ذخیره
    می‌کرد اثر نمی‌کرد — کاربر «تستِ اتصال» را با مقادیرِ درستِ فرم موفق
    می‌دید، ولی ورودِ واقعی همچنان با مقادیرِ محیطیِ نامرتبط تلاش می‌کرد.
    حالا: به‌محضِ اینکه کاربر یک‌بار از فرم ذخیره کند، همان فایل برایِ آن
    فیلد همیشه برنده است؛ متغیرهایِ محیطی فقط برایِ فیلدهایی که هنوز در
    فایل ذخیره نشده‌اند به‌کار می‌روند (سازگاریِ کاملِ با محیطِ توسعه/CI
    که هنوز هیچ فایلِ تنظیماتی نساخته)."""
    file_values = _read_settings_file()
    values = {}
    for field, env_key in _ENV_KEYS.items():
        if field in file_values:
            values[field] = file_values[field]
        else:
            env_value = os.environ.get(env_key)
            values[field] = env_value if env_value is not None else _DEFAULTS[field]
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


def create_database_if_missing(config: DatabaseConfig) -> tuple[bool, str]:
    """اگر خودِ دیتابیس (نه فقط جدول‌هایش) وجود نداشته باشد (مثلاً کاربر
    کاملاً drop‌اش کرده)، همین‌جا با اتصال به دیتابیسِ نگهداریِ postgres
    می‌سازدش. برخلافِ apply_pending_schema_files (که فقط جدول‌هایِ داخلِ
    یک دیتابیسِ از-قبل-موجود را می‌سازد)، CREATE DATABASE در پستگرس باید
    خارج از تراکنش اجرا شود — به همین دلیل isolation_level=AUTOCOMMIT."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import SQLAlchemyError

    # CREATE DATABASE نمی‌تواند پارامتری باشد (SQLAlchemy فقط برایِ مقادیر
    # جای‌گذاری می‌کند، نه شناسه‌ها) — به‌جایِ درج مستقیم در متنِ SQL، نامِ
    # دیتابیس را با یک الگویِ شناسه‌ی امن اعتبارسنجی می‌کنیم.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", config.name):
        return False, "نامِ دیتابیس باید فقط شاملِ حروفِ لاتین/رقم/زیرخط باشد و با حرف یا زیرخط شروع شود."

    maintenance_config = DatabaseConfig(
        host=config.host, port=config.port, name="postgres", user=config.user, password=config.password
    )
    try:
        engine = create_engine(maintenance_config.sqlalchemy_url, future=True, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": config.name}
            ).first()
            if exists is not None:
                engine.dispose()
                return True, "دیتابیس از قبل وجود دارد؛ کاری لازم نبود."
            conn.execute(text(f'CREATE DATABASE "{config.name}"'))
        engine.dispose()
        return True, "دیتابیس با موفقیت ساخته شد."
    except SQLAlchemyError as exc:
        return False, str(exc.__cause__ or exc)
