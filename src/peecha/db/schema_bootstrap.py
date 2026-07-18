"""اجرای خودکار db/schema/*.sql روی یک دیتابیس خالی — جایگزین اجرای دستی
فایل‌ها در pgAdmin.

فقط برای «راه‌اندازی اولیه» است، نه یک سیستم migration کامل: اگر schema
`core` از قبل وجود داشته باشد، یعنی قبلاً ساخته شده و کاری انجام نمی‌دهد
(idempotent در همین حد ساده). تغییرات ساختاریِ بعدی (وقتی دیتابیس داده‌ی
واقعی دارد) باید با Alembic migration انجام شود، نه با اجرای دوباره‌ی
همین فایل‌ها.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, text

# db/schema/ کنار پوشه‌ی src در ریشه‌ی پروژه است؛ چهار سطح از این فایل بالا می‌رویم:
# src/peecha/db/schema_bootstrap.py -> src/peecha/db -> src/peecha -> src -> (ریشه‌ی پروژه)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = _PROJECT_ROOT / "db" / "schema"


def list_schema_files() -> list[Path]:
    return sorted(SCHEMA_DIR.glob("*.sql"))


def is_initialized(engine: Engine) -> bool:
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core'")
        ).first()
    return result is not None


def initialize_schema(engine: Engine) -> None:
    """تمام فایل‌های db/schema/*.sql را به ترتیب، در یک تراکنش واحد اجرا
    می‌کند (اگر یکی خطا داد، همه‌چیز rollback می‌شود تا دیتابیس نیمه‌ساخته
    نماند)."""
    files = list_schema_files()
    if not files:
        raise FileNotFoundError(f"هیچ فایل schema‌ای در {SCHEMA_DIR} پیدا نشد.")

    with engine.begin() as conn:
        for sql_file in files:
            conn.execute(text(sql_file.read_text(encoding="utf-8")))
