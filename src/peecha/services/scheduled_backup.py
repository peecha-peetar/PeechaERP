"""R352: پشتیبان خودکار زمان‌بندی‌شده و آزمون بازیابی.

پشتیبان با همان روش پشتیبان پیش از ارتقا ساخته می‌شود (pg_dump، وگرنه پشتیبان داخلی) و کنارش تعداد ردیف هر جدول در
همان لحظه (‎.counts.json) نوشته می‌شود. آزمون بازیابی، پشتیبان را در یک دیتابیس موقت جدا بازیابی، تعداد ردیف هر جدول را
با همان فهرست مقایسه و دیتابیس موقت را حذف می‌کند؛ دیتابیس اصلی دست نمی‌خورد. زمان‌بندی وقتی برنامهٔ دسکتاپ باز است
(run_if_due)، یا با زمان‌بند سیستم‌عامل: python -m peecha.services.scheduled_backup اجرا می‌شود."""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine, create_engine, text

from peecha.db import schema_bootstrap
from peecha.db.base import new_session
from peecha.db.models.core import BackupSchedule
from peecha.services import backup as backup_service

INTERVALS = {6: "هر ۶ ساعت", 24: "روزانه", 168: "هفتگی"}


def default_folder() -> str:
    from peecha.config import SETTINGS_DIR

    return str(SETTINGS_DIR / "auto_backups")


def _row(session) -> BackupSchedule:
    row = session.get(BackupSchedule, 1)
    if row is None:
        row = BackupSchedule(schedule_id=1, is_enabled=False, interval_hours=24, keep_count=7)
        session.add(row)
    return row


@dataclass
class ScheduleRow:
    is_enabled: bool
    folder: str
    interval_hours: int
    keep_count: int
    last_backup_at: datetime.datetime | None
    last_backup_path: str | None
    last_status: str | None
    last_error: str | None
    last_check_at: datetime.datetime | None
    last_check_ok: bool | None
    last_check_note: str | None


def get_schedule() -> ScheduleRow:
    with new_session() as session:
        r = session.get(BackupSchedule, 1) or BackupSchedule(is_enabled=False, interval_hours=24, keep_count=7)
        return ScheduleRow(bool(r.is_enabled), r.folder or default_folder(), r.interval_hours, r.keep_count, r.last_backup_at,
                           r.last_backup_path, r.last_status, r.last_error, r.last_check_at, r.last_check_ok, r.last_check_note)


def save_schedule(is_enabled: bool, folder: str | None, interval_hours: int, keep_count: int) -> None:
    if interval_hours not in INTERVALS:
        raise ValueError("فاصلهٔ پشتیبان‌گیری نامعتبر است.")
    if not 1 <= keep_count <= 100:
        raise ValueError("تعداد پشتیبان‌های نگه‌داری‌شده باید بین ۱ تا ۱۰۰ باشد.")
    with new_session() as session:
        row = _row(session)
        row.is_enabled, row.folder, row.interval_hours, row.keep_count = (
            is_enabled, (folder or "").strip() or None, interval_hours, keep_count)
        session.commit()


def _counts(engine: Engine) -> dict[str, int]:
    return {t.full_name: t.row_count for t in backup_service.list_backup_tables(engine)
            if t.full_name not in backup_service.EXCLUDED_TABLES}


def _prune(folder: Path, database: str, keep: int) -> None:
    backups = sorted((p for p in folder.glob(f"{database}-auto-*") if not p.name.endswith(".counts.json")),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        old.unlink(missing_ok=True)
        Path(f"{old}.counts.json").unlink(missing_ok=True)


def run_backup(engine: Engine) -> str:
    """یک پشتیبان کامل در پوشهٔ تنظیم‌شده؛ مسیر فایل را برمی‌گرداند و نتیجه را در تنظیمات ثبت می‌کند."""
    schedule = get_schedule()
    folder = Path(schedule.folder)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        counts = _counts(engine)
        path = schema_bootstrap.dump_database(
            engine, folder, f"{engine.url.database}-auto-{now.astimezone().strftime('%Y%m%d-%H%M%S')}")
        Path(f"{path}.counts.json").write_text(json.dumps(counts, ensure_ascii=False), encoding="utf-8")
        _prune(folder, engine.url.database, schedule.keep_count)
    except Exception as exc:  # noqa: BLE001 (خطا ثبت می‌شود؛ زمان آخرین پشتیبان موفق دست نمی‌خورد تا زود دوباره تلاش شود)
        from peecha import numerals

        _record(last_status="FAILED", last_error=f"{numerals.format_jalali_datetime(now)}: {exc}"[:1000])
        raise ValueError(f"پشتیبان‌گیری ناموفق بود: {exc}") from exc
    _record(last_backup_at=now, last_backup_path=path, last_status="DONE", last_error=None)
    return path


def _record(**values) -> None:
    with new_session() as session:
        row = _row(session)
        for key, value in values.items():
            setattr(row, key, value)
        session.commit()


def is_due(schedule: ScheduleRow, now: datetime.datetime | None = None) -> bool:
    if not schedule.is_enabled:
        return False
    if schedule.last_backup_at is None:
        return True
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now - schedule.last_backup_at >= datetime.timedelta(hours=schedule.interval_hours)


def run_if_due(engine: Engine) -> str | None:
    """برای اجرای خودکار (هنگام باز بودن برنامه یا زمان‌بند سیستم‌عامل)؛ خطا فقط در تنظیمات ثبت می‌شود."""
    if not is_due(get_schedule()):
        return None
    try:
        return run_backup(engine)
    except ValueError:
        return None


@dataclass
class CheckResult:
    ok: bool
    tables_checked: int
    mismatches: list[str] = field(default_factory=list)
    note: str = ""


def _pg_restore() -> str | None:
    dump = schema_bootstrap._find_pg_dump()
    if dump:
        sibling = Path(dump).with_name(Path(dump).name.replace("pg_dump", "pg_restore"))
        if sibling.exists():
            return str(sibling)
    return shutil.which("pg_restore")


def verify_backup(engine: Engine, path: str) -> CheckResult:
    """پشتیبان را در دیتابیس موقت بازیابی و تعداد ردیف‌ها را با زمان پشتیبان‌گیری مقایسه می‌کند."""
    counts_file = Path(f"{path}.counts.json")
    if not Path(path).exists():
        raise ValueError("فایل پشتیبان پیدا نشد.")
    if counts_file.exists():
        expected = json.loads(counts_file.read_text(encoding="utf-8"))
    elif path.endswith((".json.gz", ".json")):
        with backup_service._open(path, "rt") as handle:
            expected = {t["name"]: t["row_count"] for t in json.load(handle)["manifest"]["tables"]}
    else:
        raise ValueError("فهرست تعداد ردیف‌های این پشتیبان پیدا نشد؛ فقط پشتیبان‌های خودکار قابل آزمون‌اند.")
    url = engine.url
    temp_name = f"{url.database}_restore_check"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    temp_engine = None
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{temp_name}"'))
            conn.execute(text(f'CREATE DATABASE "{temp_name}"'))
        temp_engine = create_engine(url.set(database=temp_name))
        if path.endswith(".dump"):
            tool = _pg_restore()
            if tool is None:
                raise ValueError("برنامهٔ pg_restore پیدا نشد.")
            done = subprocess.run([tool, "-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "",
                                   "-d", temp_name, "--no-owner", path], env={**os.environ, "PGPASSWORD": url.password or ""},
                                  capture_output=True, text=True, check=False)
            if done.returncode != 0:
                raise ValueError(f"بازیابی ناموفق بود: {done.stderr.strip()[:500]}")
        else:
            backup_service.import_backup(temp_engine, path)
        actual = _counts(temp_engine)
    except Exception as exc:  # noqa: BLE001
        result = CheckResult(False, 0, [], str(exc)[:1000])
    else:
        mismatches = [f"{name}: {count} ← {actual.get(name, 0)}" for name, count in sorted(expected.items())
                      if actual.get(name, 0) != count]
        result = CheckResult(not mismatches, len(expected), mismatches)
    finally:
        if temp_engine is not None:
            temp_engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{temp_name}"'))
        admin.dispose()
    note = result.note or ("" if result.ok else "اختلاف تعداد ردیف: " + "؛ ".join(result.mismatches[:10]))
    _record(last_check_at=datetime.datetime.now(datetime.timezone.utc), last_check_ok=result.ok, last_check_note=note[:2000] or None)
    return result


if __name__ == "__main__":  # زمان‌بند سیستم‌عامل
    from peecha.db.base import get_engine

    print(run_if_due(get_engine()) or "پشتیبان لازم نبود یا ناموفق بود؛ نتیجه در تنظیمات ثبت شد.")
