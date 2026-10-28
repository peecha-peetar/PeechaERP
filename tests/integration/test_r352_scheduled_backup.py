"""R352: پشتیبان خودکار و آزمون بازیابی: اعتبار تنظیم، سررسید بر اساس فاصله، پشتیبان pg_dump و داخلی با فهرست تعداد
ردیف، نگه‌داری فقط N پشتیبان آخر، آزمون بازیابی در دیتابیس موقت (درست و دست‌کاری‌شده)، ثبت خطای پشتیبان، و فرم."""
import datetime, json, os, sys, tempfile, time
from pathlib import Path
os.environ["PEECHA_DB_NAME"] = "peecha_test_r352"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403

from peecha.services import scheduled_backup as sb

engine = get_engine()
receive(byp, 5, 100_000)
folder = tempfile.mkdtemp(prefix="r352_auto_")
check(raises(lambda: sb.save_schedule(True, folder, 5, 3), "فاصله") and raises(lambda: sb.save_schedule(True, folder, 24, 0), "۱۰۰"),
      "interval and retention are validated")
check(not sb.is_due(sb.get_schedule()) and sb.run_if_due(engine) is None, "a disabled schedule never runs")
sb.save_schedule(True, folder, 24, 2)
schedule = sb.get_schedule()
check(schedule.folder == folder and schedule.keep_count == 2 and sb.is_due(schedule), "an enabled schedule without a backup is due")

first = sb.run_if_due(engine)
schedule = sb.get_schedule()
counts = json.loads(Path(f"{first}.counts.json").read_text(encoding="utf-8"))
check(first.endswith(".dump") and schedule.last_status == "DONE" and schedule.last_backup_path == first
      and counts.get("inv.items", 0) >= 6, f"a pg_dump backup with the row counts is taken ({first})")
check(not sb.is_due(schedule) and sb.is_due(schedule, schedule.last_backup_at + datetime.timedelta(hours=25)),
      "the next one is due after the interval")

result = sb.verify_backup(engine, first)
check(result.ok and result.tables_checked == len(counts) and sb.get_schedule().last_check_ok,
      f"the dump restores into a temporary database with identical row counts ({result.note} {result.mismatches[:3]})")
with engine.connect() as conn:
    leftover = conn.execute(text("SELECT count(*) FROM pg_database WHERE datname = 'peecha_test_r352_restore_check'")).scalar()
check(leftover == 0, "the temporary database is dropped")

tampered = dict(counts, **{"inv.items": counts["inv.items"] + 1})
Path(f"{first}.counts.json").write_text(json.dumps(tampered), encoding="utf-8")
bad = sb.verify_backup(engine, first)
check(not bad.ok and any("inv.items" in m for m in bad.mismatches) and sb.get_schedule().last_check_ok is False
      and "inv.items" in sb.get_schedule().last_check_note, "a count difference fails the check and is recorded")

os.environ["PEECHA_PG_DUMP"] = "none"
try:
    time.sleep(1.1)
    internal = sb.run_backup(engine)
    time.sleep(1.1)
    newest = sb.run_backup(engine)
finally:
    del os.environ["PEECHA_PG_DUMP"]
check(internal.endswith(".json.gz") and sb.verify_backup(engine, newest).ok, "the internal backup restores and checks too")
remaining = sorted(p.name for p in Path(folder).iterdir() if not p.name.endswith(".counts.json"))
check(len(remaining) == 2 and Path(first).name not in remaining
      and len(list(Path(folder).glob("*.counts.json"))) == 2, f"only the last two backups are kept ({remaining})")

sb.save_schedule(True, "/proc/peecha-cannot-write", 24, 2)
check(raises(lambda: sb.run_backup(engine), "ناموفق") and sb.get_schedule().last_status == "FAILED"
      and sb.run_if_due(engine) is None, "a failed backup is recorded and the automatic run stays quiet")
sb.save_schedule(True, folder, 24, 2)

# فرم
from PySide6.QtWidgets import QApplication, QPushButton
qapp = QApplication.instance() or QApplication([])
from peecha.ui.screens.system_backup import SystemBackupScreen

screen = SystemBackupScreen()
screen.refresh()
names = {b.accessibleName() for b in screen.findChildren(QPushButton)}
check(screen.auto_enabled.isChecked() and screen.auto_folder.text() == folder and screen.auto_keep.value() == 2
      and "آزمون بازیابی آخرین پشتیبان در دیتابیس موقت" in names and "آخرین آزمون بازیابی" in screen.auto_status.text(),
      "the backup screen shows the schedule, the last results and the buttons")

finish()
