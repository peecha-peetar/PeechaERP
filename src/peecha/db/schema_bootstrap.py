"""اجرای خودکار db/schema/*.sql روی دیتابیس — جایگزین اجرای دستی فایل‌ها
در pgAdmin.

برای دیتابیس کاملاً خالی همهٔ فایل‌ها اجرا می‌شوند. برای دیتابیسی که از
قبل ساخته شده (core از پیش وجود دارد) اما فایل‌های schema تازه‌تری بعداً
به db/schema اضافه شده‌اند (مثلاً یک جدول جدید مثل audit.activity_log)،
فقط همان فایل‌های جدید اجرا می‌شوند — بدون نیاز به Alembic و بدون خطر
اجرای دوبارهٔ فایل‌های قدیمی (که با «already exists» شکست می‌خورد).

ردیابی این‌که کدام فایل قبلاً اجرا شده در public.peecha_schema_migrations
نگه‌داری می‌شود (عمداً در schema پیش‌فرض public، نه core — چون روی
دیتابیس کاملاً خالی، خود core هم هنوز وجود ندارد). برای دیتابیسی که از
قبل ساخته شده اما این جدول ردیابی را ندارد (یعنی قبل از اضافه‌شدن همین
مکانیزم ساخته شده)، هر فایل با «نشانه»‌اش (اولین CREATE SCHEMA/CREATE
TABLE که تعریف می‌کند) بررسی می‌شود تا بدون اجرای دوباره، applied علامت
بخورد.

R335 — ارتقای امن نزد مشتری:
- فقط یک سیستم در هر لحظه ارتقا می‌دهد (قفل pg_advisory)؛ بقیه منتظر می‌مانند یا پیام «در جریان است» می‌گیرند.
- اگر فایل تازه‌ای برای اجرا هست و دیتابیس خالی نیست، اول خودکار پشتیبان گرفته می‌شود (pg_dump، وگرنه
  پشتیبان داخلی برنامه) و پنج پشتیبان آخر نگه داشته می‌شود؛ بدون پشتیبان ارتقا انجام نمی‌شود.
- برنامه‌ای که از دیتابیس قدیمی‌تر است (دیتابیس فایل شماره‌بالاتری از آخرین فایل خودش دارد) اجازهٔ کار ندارد.
- اثر انگشت هر فایل ثبت می‌شود تا ویرایش فایل منتشرشده دیده شود؛ هر ارتقا در public.peecha_schema_upgrades
  با نسخه، سیستم، فایل‌ها، پشتیبان و نتیجه ثبت می‌شود."""

from __future__ import annotations

import datetime
import glob
import hashlib
import os
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
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
_TRACKING_COLUMNS_DDL = (
    "ALTER TABLE public.peecha_schema_migrations ADD COLUMN IF NOT EXISTS checksum TEXT",
    "ALTER TABLE public.peecha_schema_migrations ADD COLUMN IF NOT EXISTS app_version TEXT",
)
_UPGRADES_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS public.peecha_schema_upgrades ("
    "upgrade_id BIGSERIAL PRIMARY KEY, started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ, "
    "app_version TEXT, source TEXT, host TEXT, files TEXT[] NOT NULL DEFAULT '{}', backup_path TEXT, "
    "status TEXT NOT NULL, error TEXT)"
)
_LOCK_KEY = 7_335_335  # قفل سراسری ارتقا؛ فقط یک فرایند در هر لحظه
KEEP_BACKUPS = 5
_SCHEMA_MARKER_RE = re.compile(r"CREATE SCHEMA (\w+)", re.IGNORECASE)
_TABLE_MARKER_RE = re.compile(r"CREATE TABLE (\w+)\.(\w+)", re.IGNORECASE)


def list_schema_files() -> list[Path]:
    return sorted(SCHEMA_DIR.glob("*.sql"))


class SchemaUpgradeError(RuntimeError):
    """خطای ارتقای دیتابیس با پیام فارسی قابل نمایش به کاربر."""


class SchemaUpgradeBusy(SchemaUpgradeError):
    pass


class SchemaNewerThanApp(SchemaUpgradeError):
    pass


class SchemaBackupFailed(SchemaUpgradeError):
    pass


def _app_version() -> str:
    from peecha.version import APP_VERSION

    return APP_VERSION


def _number(name: str) -> int | None:
    m = re.match(r"(\d+)_", name)
    return int(m.group(1)) if m else None


def file_checksum(path: Path) -> str:
    """اثر انگشت محتوا؛ پایان خط ویندوز و فاصلهٔ آخر فایل اثری ندارد."""
    body = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _tracking_state(conn) -> dict[str, str | None] | None:
    """نام فایل ← اثر انگشت ثبت‌شده؛ None یعنی جدول ردیابی یا ستون اثر انگشت هنوز نیست."""
    has_column = conn.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name = 'peecha_schema_migrations' AND column_name = 'checksum'")).first()
    if has_column is None:
        return None
    return dict(conn.execute(text("SELECT filename, checksum FROM public.peecha_schema_migrations")).all())


def _last_upgrade_version(conn) -> str | None:
    exists = conn.execute(text("SELECT to_regclass('public.peecha_schema_upgrades')")).scalar()
    if not exists:
        return None
    return conn.execute(text("SELECT app_version FROM public.peecha_schema_upgrades WHERE status = 'DONE' "
                             "ORDER BY upgrade_id DESC LIMIT 1")).scalar()


def _newer_files(applied, files: list[Path]) -> list[str]:
    top = max((_number(f.name) or 0) for f in files)
    return sorted(n for n in applied if (_number(n) or 0) > top)


def _guard_newer(conn, applied, files: list[Path]) -> None:
    newer = _newer_files(applied, files)
    if newer:
        version = _last_upgrade_version(conn)
        version = version if version and version != _app_version() else None
        raise SchemaNewerThanApp(
            f"دیتابیس با نسخهٔ تازه‌تری از برنامه{f' ({version})' if version else ''} ارتقا یافته و برنامهٔ این سیستم "
            f"({_app_version()}) قدیمی‌تر است. برای این‌که اطلاعات ناقص ثبت نشود، ورود بسته شد؛ برنامهٔ این سیستم را "
            "به‌روز کنید.")


def pending_schema_files(engine: Engine) -> list[str]:
    """فایل‌هایی که روی این دیتابیس هنوز اجرا نشده‌اند (فقط خواندن)."""
    files = list_schema_files()
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT to_regclass('public.peecha_schema_migrations')")).scalar()
        applied = set(conn.execute(text("SELECT filename FROM public.peecha_schema_migrations")).scalars()) \
            if exists else set()
    if not applied and exists is None and is_initialized(engine):
        return []  # دیتابیس قدیمی‌تر از جدول ردیابی؛ اجرای اصلی فایل‌های موجود را خودش علامت می‌زند
    return [f.name for f in files if f.name not in applied]


def is_initialized(engine: Engine) -> bool:
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core'")
        ).first()
    return result is not None


def _marker_exists(conn, sql_text: str) -> bool:
    """آیا نشانهٔ این فایل (اولین schema/جدولی که می‌سازد) از قبل در
    دیتابیس هست — برای دیتابیسی که قدیمی‌تر از جدول ردیابی است."""
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


def apply_pending_schema_files(engine: Engine, *, source: str = "desktop", backup: bool = True,
                               wait_seconds: float = 0.0) -> list[str]:
    """فایل‌های db/schema/*.sql‌ای که هنوز روی این دیتابیس اجرا نشده‌اند را
    اجرا می‌کند و نام‌شان را برمی‌گرداند (خالی یعنی چیزی برای اجرا نبود).
    امن است که در هر بار بالا آمدن برنامه صدا زده شود.

    source: desktop | api | settings | restore — فقط برای دفترچهٔ ارتقا.
    backup: پشتیبان پیش از ارتقا (بازیابی پشتیبان آن را لازم ندارد).
    wait_seconds: اگر سیستم دیگری در حال ارتقاست، تا این مدت صبر می‌شود."""
    files = list_schema_files()
    if not files:
        raise FileNotFoundError(f"هیچ فایل schema‌ای در {SCHEMA_DIR} پیدا نشد.")

    with engine.connect() as conn:  # مسیر سریع هر ورود: فقط خواندن، بدون قفل
        state = _tracking_state(conn)
        if state is not None:
            _guard_newer(conn, state, files)
            if all(f.name in state for f in files) and all(state.values()):
                return []

    with engine.connect() as lock_conn:
        deadline = time.monotonic() + wait_seconds
        while not lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).scalar():
            lock_conn.commit()
            if time.monotonic() >= deadline:
                raise SchemaUpgradeBusy("سیستم دیگری همین حالا در حال ارتقای دیتابیس است؛ چند دقیقهٔ دیگر دوباره "
                                        "وارد شوید.")
            time.sleep(1)
        lock_conn.commit()
        try:
            return _upgrade_locked(engine, files, source, backup)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
            lock_conn.commit()


def _upgrade_locked(engine: Engine, files: list[Path], source: str, backup: bool) -> list[str]:
    fresh = not is_initialized(engine)
    with engine.begin() as conn:
        conn.execute(text(_MIGRATIONS_TABLE_DDL))
        for ddl in _TRACKING_COLUMNS_DDL:
            conn.execute(text(ddl))
        conn.execute(text(_UPGRADES_TABLE_DDL))
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

        _guard_newer(conn, already_applied, files)
        # فایل‌های قدیمی که هنوز اثر انگشت ندارند، با محتوای فعلی ثبت می‌شوند
        for sql_file in files:
            if sql_file.name in already_applied:
                conn.execute(text("UPDATE public.peecha_schema_migrations SET checksum = :c "
                                  "WHERE filename = :f AND checksum IS NULL"),
                             {"c": file_checksum(sql_file), "f": sql_file.name})
    pending = [f for f in files if f.name not in already_applied]
    if not pending:
        return []

    names = [f.name for f in pending]
    backup_path = None
    if backup and not fresh and os.environ.get("PEECHA_UPGRADE_BACKUP", "").lower() not in ("off", "0", "no"):
        try:
            backup_path = backup_before_upgrade(engine, names[0])
        except Exception as exc:  # noqa: BLE001 -- بدون پشتیبان ارتقا انجام نمی‌شود
            _log_upgrade(engine, source, names, None, "FAILED", f"پشتیبان گرفته نشد: {exc}")
            raise SchemaBackupFailed(f"پیش از ارتقا پشتیبان گرفته نشد، پس برای حفظ اطلاعات ارتقا انجام نشد. علت: {exc}") \
                from exc

    upgrade_id = _log_upgrade(engine, source, names, backup_path, "RUNNING", None)
    try:
        with engine.begin() as conn:  # همهٔ فایل‌ها با هم؛ خطای یکی یعنی برگشت همه
            for sql_file in pending:
                conn.execute(text(sql_file.read_text(encoding="utf-8")))
                conn.execute(
                    text("INSERT INTO public.peecha_schema_migrations (filename, checksum, app_version) "
                         "VALUES (:f, :c, :v)"),
                    {"f": sql_file.name, "c": file_checksum(sql_file), "v": _app_version()},
                )
            conn.execute(text("UPDATE public.peecha_schema_upgrades SET status = 'DONE', finished_at = now() "
                              "WHERE upgrade_id = :u"), {"u": upgrade_id})
    except Exception as exc:
        with engine.begin() as conn:
            conn.execute(text("UPDATE public.peecha_schema_upgrades SET status = 'FAILED', finished_at = now(), "
                              "error = :e WHERE upgrade_id = :u"), {"u": upgrade_id, "e": str(exc)[:4000]})
        raise
    return names


def _log_upgrade(engine: Engine, source: str, names: list[str], backup_path: str | None, status: str,
                 error: str | None) -> int:
    with engine.begin() as conn:
        return conn.execute(text(
            "INSERT INTO public.peecha_schema_upgrades (app_version, source, host, files, backup_path, status, error, "
            "finished_at) VALUES (:v, :s, :h, :f, :b, :st, :e, CASE WHEN :st = 'RUNNING' THEN NULL ELSE now() END) "
            "RETURNING upgrade_id"),
            {"v": _app_version(), "s": source, "h": socket.gethostname(), "f": names, "b": backup_path, "st": status,
             "e": error}).scalar()


# --- پشتیبان پیش از ارتقا ------------------------------------------------------------------------------
def backup_dir() -> Path:
    from peecha.config import SETTINGS_DIR

    return Path(os.environ.get("PEECHA_UPGRADE_BACKUP_DIR") or SETTINGS_DIR / "upgrade_backups")


def _find_pg_dump() -> str | None:
    chosen = os.environ.get("PEECHA_PG_DUMP")
    if chosen:
        return None if chosen.lower() == "none" else chosen
    found = shutil.which("pg_dump")
    if found:
        return found
    candidates = glob.glob(r"C:\Program Files\PostgreSQL\*\bin\pg_dump.exe")
    return max(candidates, key=lambda p: _number(Path(p).parent.parent.name + "_") or 0) if candidates else None


def backup_before_upgrade(engine: Engine, first_file: str) -> str:
    """پشتیبان کامل پیش از ارتقا؛ pg_dump اگر هست (قالب custom برای pg_restore)، وگرنه پشتیبان داخلی برنامه."""
    folder = backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    url = engine.url
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{url.database}-before-{first_file.rsplit('.', 1)[0]}-{stamp}"
    pg_dump = _find_pg_dump()
    if pg_dump:
        path = folder / f"{base}.dump"
        env = {**os.environ, "PGPASSWORD": url.password or ""}
        cmd = [pg_dump, "-Fc", "-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "",
               "-f", str(path), url.database]
        try:
            done = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        except OSError:
            done = None
        if done is not None and done.returncode == 0 and path.exists() and path.stat().st_size > 0:
            _prune_backups(folder, url.database)
            return str(path)
        path.unlink(missing_ok=True)  # مثلاً نسخهٔ pg_dump با سرور نمی‌خواند: پشتیبان داخلی
    from peecha.services import backup as backup_service

    path = folder / f"{base}.json.gz"
    backup_service.export_backup(engine, str(path))
    _prune_backups(folder, url.database)
    return str(path)


def _prune_backups(folder: Path, database: str) -> None:
    mine = sorted(folder.glob(f"{database}-before-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in mine[KEEP_BACKUPS:]:
        old.unlink(missing_ok=True)


# --- وضعیت برای نمایش ---------------------------------------------------------------------------------
@dataclass
class UpgradeRow:
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    app_version: str | None
    source: str | None
    host: str | None
    files: list[str]
    backup_path: str | None
    status: str
    error: str | None


@dataclass
class SchemaStatus:
    applied: int
    latest: str | None
    pending: list[str]
    changed: list[str]  # فایل منتشرشده‌ای که پس از اجرا ویرایش شده است
    newer: list[str]  # فایل‌هایی در دیتابیس که این برنامه نمی‌شناسد (دیتابیس از برنامه جلوتر است)
    upgrades: list[UpgradeRow] = field(default_factory=list)


def schema_status(engine: Engine, limit: int = 30) -> SchemaStatus:
    files = list_schema_files()
    with engine.connect() as conn:
        state = _tracking_state(conn) or {}
        upgrades = []
        if conn.execute(text("SELECT to_regclass('public.peecha_schema_upgrades')")).scalar():
            upgrades = [UpgradeRow(r[0], r[1], r[2], r[3], r[4], list(r[5] or []), r[6], r[7], r[8]) for r in conn.execute(text(
                "SELECT started_at, finished_at, app_version, source, host, files, backup_path, status, error "
                "FROM public.peecha_schema_upgrades ORDER BY upgrade_id DESC LIMIT :n"), {"n": limit}).all()]
    changed = [f.name for f in files if state.get(f.name) and state[f.name] != file_checksum(f)]
    applied = sorted(state, key=lambda n: (_number(n) or 0, n))
    return SchemaStatus(len(state), applied[-1] if applied else None, [f.name for f in files if f.name not in state],
                        changed, _newer_files(state, files), upgrades)


def initialize_schema(engine: Engine) -> None:
    """نگه‌داشته‌شده برای سازگاری با فراخوانی‌های قبلی (دکمهٔ «ساخت
    جدول‌ها» در تنظیمات اتصال) — اکنون فقط apply_pending_schema_files را
    صدا می‌زند که هم دیتابیس خالی و هم دیتابیس نیازمند فایل‌های تازه را
    یکسان پوشش می‌دهد."""
    apply_pending_schema_files(engine)
