"""اجرای خودکار db/schema/*.sql روی دیتابیس — جایگزین اجرای دستی فایل‌ها
در pgAdmin.

برای دیتابیسِ کاملاً خالی همه‌ی فایل‌ها اجرا می‌شوند. برای دیتابیسی که از
قبل ساخته شده (core از پیش وجود دارد) اما فایل‌های schema تازه‌تری بعداً
به db/schema اضافه شده‌اند (مثلاً یک جدولِ جدید مثلِ audit.activity_log)،
فقط همان فایل‌های جدید اجرا می‌شوند — بدونِ نیاز به Alembic و بدونِ خطر
اجرای دوباره‌ی فایل‌های قدیمی (که با «already exists» شکست می‌خورد).

ردیابی این‌که کدام فایل قبلاً اجرا شده در public.peecha_schema_migrations
نگه‌داری می‌شود (عمداً در schema پیش‌فرضِ public، نه core — چون روی
دیتابیسِ کاملاً خالی، خودِ core هم هنوز وجود ندارد). برای دیتابیسی که از
قبل ساخته شده اما این جدولِ ردیابی را ندارد (یعنی قبل از اضافه‌شدنِ همین
مکانیزم ساخته شده)، هر فایل با «نشانه»‌اش (اولین CREATE SCHEMA/CREATE
TABLE که تعریف می‌کند) بررسی می‌شود تا بدونِ اجرای دوباره، applied علامت
بخورد."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import Engine, text

# db/schema/ کنار پوشه‌ی src در ریشه‌ی پروژه است؛ چهار سطح از این فایل بالا می‌رویم:
# src/peecha/db/schema_bootstrap.py -> src/peecha/db -> src/peecha -> src -> (ریشه‌ی پروژه)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = _PROJECT_ROOT / "db" / "schema"

_MIGRATIONS_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS public.peecha_schema_migrations ("
    "filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
)
_SCHEMA_MARKER_RE = re.compile(r"CREATE SCHEMA (\w+)", re.IGNORECASE)
_TABLE_MARKER_RE = re.compile(r"CREATE TABLE (\w+)\.(\w+)", re.IGNORECASE)


def list_schema_files() -> list[Path]:
    return sorted(SCHEMA_DIR.glob("*.sql"))


def is_initialized(engine: Engine) -> bool:
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core'")
        ).first()
    return result is not None


def _marker_exists(conn, sql_text: str) -> bool:
    """آیا نشانه‌ی این فایل (اولین schema/جدولی که می‌سازد) از قبل در
    دیتابیس هست — برای دیتابیسی که قدیمی‌تر از جدولِ ردیابی است."""
    schema_match = _SCHEMA_MARKER_RE.search(sql_text)
    if schema_match:
        return (
            conn.execute(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
                {"s": schema_match.group(1)},
            ).first()
            is not None
        )
    table_match = _TABLE_MARKER_RE.search(sql_text)
    if table_match:
        schema_name, table_name = table_match.groups()
        return (
            conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_schema = :s AND table_name = :t"),
                {"s": schema_name, "t": table_name},
            ).first()
            is not None
        )
    return False


def apply_pending_schema_files(engine: Engine) -> list[str]:
    """فایل‌های db/schema/*.sql‌ای که هنوز روی این دیتابیس اجرا نشده‌اند را
    اجرا می‌کند و نام‌شان را برمی‌گرداند (خالی یعنی چیزی برای اجرا نبود).
    امن است که در هر بارِ بالا آمدنِ برنامه صدا زده شود."""
    files = list_schema_files()
    if not files:
        raise FileNotFoundError(f"هیچ فایل schema‌ای در {SCHEMA_DIR} پیدا نشد.")

    newly_applied: list[str] = []
    with engine.begin() as conn:
        conn.execute(text(_MIGRATIONS_TABLE_DDL))
        already_applied = {
            row[0] for row in conn.execute(text("SELECT filename FROM public.peecha_schema_migrations"))
        }

        # بازپرکردنِ جدولِ ردیابی برای دیتابیسی که از قبلِ وجودِ این مکانیزم
        # ساخته شده: هر فایلی که نشانه‌اش از قبل هست را بدونِ اجرا applied کن.
        if not already_applied:
            for sql_file in files:
                sql_text = sql_file.read_text(encoding="utf-8")
                if _marker_exists(conn, sql_text):
                    conn.execute(
                        text("INSERT INTO public.peecha_schema_migrations (filename) VALUES (:f)"),
                        {"f": sql_file.name},
                    )
                    already_applied.add(sql_file.name)

        for sql_file in files:
            if sql_file.name in already_applied:
                continue
            conn.execute(text(sql_file.read_text(encoding="utf-8")))
            conn.execute(
                text("INSERT INTO public.peecha_schema_migrations (filename) VALUES (:f)"),
                {"f": sql_file.name},
            )
            newly_applied.append(sql_file.name)

    return newly_applied


def initialize_schema(engine: Engine) -> None:
    """نگه‌داشته‌شده برای سازگاری با فراخوانی‌های قبلی (دکمه‌ی «ساختِ
    جدول‌ها» در تنظیماتِ اتصال) — اکنون فقط apply_pending_schema_files را
    صدا می‌زند که هم دیتابیسِ خالی و هم دیتابیسِ نیازمندِ فایل‌های تازه را
    یکسان پوشش می‌دهد."""
    apply_pending_schema_files(engine)
