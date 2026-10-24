"""R335: ارتقای امن دیتابیس نزد مشتری: دیتابیس یک نسخه عقب‌تر با اطلاعات واقعی ارتقا می‌یابد و هیچ ردیف قبلی تغییر
نمی‌کند؛ پیش از ارتقا پشتیبان کامل گرفته می‌شود که قابل بازیابی است؛ خطای یک فایل همه را برمی‌گرداند؛ قفل هم‌زمانی،
جلوگیری از نسخهٔ قدیمی (دسکتاپ و سرور موبایل)، اثر انگشت فایل‌ها، دفترچهٔ ارتقا و صفحهٔ پشتیبان."""
import collections, gzip, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

os.environ["PEECHA_DB_NAME"] = "peecha_test_r335"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BACKUPS = tempfile.mkdtemp(prefix="r335_backups_")
os.environ["PEECHA_UPGRADE_BACKUP_DIR"] = BACKUPS
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

from peecha.db import schema_bootstrap as sb  # noqa: E402

REAL_DIR = sb.SCHEMA_DIR
REAL_FILES = sb.list_schema_files()
LAST = REAL_FILES[-1]
OLD_DIR = Path(tempfile.mkdtemp(prefix="r335_schema_old_"))
for f in REAL_FILES[:-1]:
    shutil.copy(f, OLD_DIR / f.name)
sb.SCHEMA_DIR = OLD_DIR  # دیتابیس مشتری: یک نسخه عقب‌تر

from prd_fixture import *  # noqa: F401,F403,E402

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication([])
for _name in ("warning", "information", "critical"):
    setattr(QMessageBox, _name, staticmethod(lambda *a, **k: QMessageBox.Ok))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from sqlalchemy import inspect as sa_inspect  # noqa: E402

from peecha.version import APP_VERSION  # noqa: E402

engine = get_engine()
receive(r1, D(40), D(1200))
receive(fg, D(5), D(90000), wh=wh_fg)


def fingerprint():
    """جدول ← ردیف‌ها (فقط ستون‌هایی که پیش از ارتقا بودند)."""
    insp = sa_inspect(engine)
    out = {}
    with engine.connect() as conn:
        for schema in insp.get_schema_names():
            if schema in ("information_schema", "pg_catalog", "pg_toast"):
                continue
            for table in insp.get_table_names(schema=schema):
                if table.startswith("peecha_schema"):
                    continue
                cols = [c["name"] for c in insp.get_columns(table, schema=schema)]
                out[f"{schema}.{table}"] = cols
    return out


def rows(spec, db_engine=None):
    data = {}
    with (db_engine or engine).connect() as conn:
        for name, cols in spec.items():
            schema, table = name.split(".")
            sel = ", ".join(f'"{c}"' for c in cols)
            data[name] = collections.Counter(conn.execute(text(f'SELECT ROW({sel})::text FROM "{schema}"."{table}"')).scalars())
    return data


def last_upgrade():
    with engine.connect() as conn:
        return conn.execute(text("SELECT status, files, backup_path, app_version, source, error FROM "
                                 "public.peecha_schema_upgrades ORDER BY upgrade_id DESC LIMIT 1")).first()


def tracking(name):
    with engine.connect() as conn:
        return conn.execute(text("SELECT checksum, app_version FROM public.peecha_schema_migrations WHERE filename = :f"),
                            {"f": name}).first()


def use_dir(extra: dict[str, str] | None = None, changed: dict[str, str] | None = None) -> Path:
    folder = Path(tempfile.mkdtemp(prefix="r335_schema_"))
    for f in REAL_FILES:
        shutil.copy(f, folder / f.name)
    for name, body in (extra or {}).items():
        (folder / name).write_text(body, encoding="utf-8")
    for name, body in (changed or {}).items():
        (folder / name).write_bytes(body.encode("utf-8"))
    sb.SCHEMA_DIR = folder
    return folder


def sql(statement, **params):
    with engine.begin() as conn:
        return conn.execute(text(statement), params)


# --- ۱: ارتقای دیتابیس پر از اطلاعات ---------------------------------------------------------------------------------
check(tracking(LAST.name) is None and sb.pending_schema_files(engine) == [], "the customer database is one release behind")
spec = fingerprint()
before = rows(spec)
check(sum(sum(c.values()) for c in before.values()) > 100, "it holds real data (company, accounts, items, stock)")
sb.SCHEMA_DIR = REAL_DIR
check(sb.pending_schema_files(engine) == [LAST.name], "the new release brings one new file")
applied = sb.apply_pending_schema_files(engine, source="desktop")
check(applied == [LAST.name], f"the new file is applied ({applied})")
after = rows(spec)
lost = {name: before[name] - after[name] for name in spec if before[name] - after[name]}
check(not lost, f"no existing row changed or disappeared ({list(lost)[:5]})")
cols = {c["name"] for c in sa_inspect(engine).get_columns("distribution_runs", schema="comm")}
check({"start_latitude", "start_longitude"} <= cols, "the new columns are there")
status, files, backup_path, version, source, error = last_upgrade()
check(status == "DONE" and list(files) == [LAST.name] and version == APP_VERSION and source == "desktop",
      f"the upgrade log says what ran, from where and with which version ({status}, {version})")
check(backup_path and backup_path.endswith(".dump") and Path(backup_path).stat().st_size > 0 and
      Path(backup_path).parent == Path(BACKUPS), f"a full backup was taken before the upgrade ({backup_path})")
check(tracking(LAST.name)[0] == sb.file_checksum(LAST) and tracking(REAL_FILES[0].name)[0],
      "every file has its fingerprint, old ones too")

# پشتیبان واقعاً بازیابی می‌شود و همان اطلاعات پیش از ارتقا را دارد
restore_db = "peecha_test_r335_restore"
env = {**os.environ, "PGPASSWORD": "peecha"}
subprocess.run(["psql", "-h", "localhost", "-U", "peecha", "-d", "postgres", "-qc", f"DROP DATABASE IF EXISTS {restore_db}"],
               env=env, check=True, capture_output=True)
subprocess.run(["psql", "-h", "localhost", "-U", "peecha", "-d", "postgres", "-qc", f"CREATE DATABASE {restore_db}"],
               env=env, check=True, capture_output=True)
done = subprocess.run(["pg_restore", "-h", "localhost", "-U", "peecha", "-d", restore_db, "--no-owner", backup_path],
                      env=env, capture_output=True, text=True)
from sqlalchemy import create_engine  # noqa: E402

restored_engine = create_engine(engine.url.set(database=restore_db))
restored = rows(spec, restored_engine)
restored_engine.dispose()
check(done.returncode == 0 and restored == before, f"the backup restores the exact data from before the upgrade ({done.stderr[:200]})")
subprocess.run(["psql", "-h", "localhost", "-U", "peecha", "-d", "postgres", "-qc", f"DROP DATABASE IF EXISTS {restore_db}"],
               env=env, capture_output=True)

# --- ۲: ورودهای بعدی: بدون کار اضافه ----------------------------------------------------------------------------------
count = len(list(Path(BACKUPS).iterdir()))
started = time.monotonic()
check(sb.apply_pending_schema_files(engine) == [] and len(list(Path(BACKUPS).iterdir())) == count and
      last_upgrade()[1] == [LAST.name], "the next logins do nothing (no new backup, no new log row)")
check(time.monotonic() - started < 2, "and they are quick")

# --- ۳: نسخهٔ قدیمی روی دیتابیس تازه‌تر کار نمی‌کند -------------------------------------------------------------------------
sql("INSERT INTO public.peecha_schema_migrations (filename, checksum) VALUES ('999_future.sql', 'x')")
try:
    sb.apply_pending_schema_files(engine)
    blocked = None
except sb.SchemaNewerThanApp as exc:
    blocked = str(exc)
check(blocked and "به‌روز کنید" in blocked and APP_VERSION in blocked, f"an older program is stopped with a clear message ({blocked})")
check(sb.schema_status(engine).newer == ["999_future.sql"], "the backup page lists what the program does not know")
from peecha.ui.login_window import LoginWindow  # noqa: E402

login = LoginWindow("Vazirmatn")
check(login.schema_blocked and "به‌روز کنید" in login.status_label.text(), "the login screen shows it and blocks login")
sess.current_user = None
login.username_field.setText("admin")
login.password_field.setText("secret123")
login._attempt_login()
check(sess.current_user is None, "logging in is refused while the program is older than the database")
import peecha_api.main as api  # noqa: E402

try:
    api._upgrade_database()
    api_blocked = False
except sb.SchemaNewerThanApp:
    api_blocked = True
check(api_blocked, "the mobile server does not start either")
sql("DELETE FROM public.peecha_schema_migrations WHERE filename = '999_future.sql'")
login._attempt_login()
check(login.schema_blocked is None and sess.current_user is not None, "after updating, login works again")
for w in QApplication.topLevelWidgets():
    w.hide()
api._upgrade_database()
check(True, "the mobile server upgrades the database on start (nothing left to do)")

# --- ۴: سیستم دیگری در حال ارتقاست ------------------------------------------------------------------------------------------
use_dir({"996_extra.sql": "CREATE TABLE public.r335_extra (id INTEGER);"})
holder = engine.connect()
holder.execute(text("SELECT pg_advisory_lock(7335335)"))
holder.commit()
try:
    sb.apply_pending_schema_files(engine, wait_seconds=0)
    busy = None
except sb.SchemaUpgradeBusy as exc:
    busy = str(exc)
check(busy and "در حال ارتقا" in busy, f"while another system upgrades, this one waits and is told so ({busy})")
holder.execute(text("SELECT pg_advisory_unlock(7335335)"))
holder.commit()
holder.close()
check(sb.apply_pending_schema_files(engine, wait_seconds=5) == ["996_extra.sql"], "once it is free, the upgrade runs")

# --- ۵: خطا در یک فایل: هیچ‌چیز تغییر نمی‌کند ---------------------------------------------------------------------------------
use_dir({"996_extra.sql": "CREATE TABLE public.r335_extra (id INTEGER);",
         "997_ok.sql": "CREATE TABLE public.r335_ok (id INTEGER);",
         "998_bad.sql": "CREATE TABLE public.r335_half (id INTEGER); SELECT 1/0;"})
try:
    sb.apply_pending_schema_files(engine)
    failed = False
except Exception:  # noqa: BLE001
    failed = True
with engine.connect() as conn:
    left = conn.execute(text("SELECT to_regclass('public.r335_ok'), to_regclass('public.r335_half')")).first()
status, files, backup_path, *_rest, error = last_upgrade()
check(failed and left == (None, None) and tracking("997_ok.sql") is None and tracking("998_bad.sql") is None,
      "a failing file rolls back every file of the upgrade")
check(status == "FAILED" and "division by zero" in (error or "") and backup_path, "the log keeps the failure and the backup")

# --- ۶: پشتیبان داخلی وقتی pg_dump نیست؛ فقط پنج پشتیبان آخر ------------------------------------------------------------------
for i in range(7):
    old = Path(BACKUPS) / f"{engine.url.database}-before-000_old{i}-20000101-00000{i}.dump"
    old.write_text("old")
    os.utime(old, (1_000_000 + i, 1_000_000 + i))
use_dir({"996_extra.sql": "CREATE TABLE public.r335_extra (id INTEGER);",
         "997_ok.sql": "CREATE TABLE public.r335_ok (id INTEGER);"})
os.environ["PEECHA_PG_DUMP"] = "none"
check(sb.apply_pending_schema_files(engine) == ["997_ok.sql"], "the upgrade runs with the built-in backup")
os.environ.pop("PEECHA_PG_DUMP")
backup_path = last_upgrade()[2]
with gzip.open(backup_path, "rt", encoding="utf-8") as fh:
    payload = json.load(fh)
check(backup_path.endswith(".json.gz") and payload["manifest"]["tables"], "without pg_dump the program's own backup is used")
mine = list(Path(BACKUPS).glob(f"{engine.url.database}-before-*"))
check(len(mine) == sb.KEEP_BACKUPS and Path(backup_path) in mine, f"only the last five backups are kept ({len(mine)})")

# --- ۷: بدون پشتیبان ارتقا انجام نمی‌شود ------------------------------------------------------------------------------------
use_dir({"996_extra.sql": "CREATE TABLE public.r335_extra (id INTEGER);",
         "997_ok.sql": "CREATE TABLE public.r335_ok (id INTEGER);",
         "998_more.sql": "CREATE TABLE public.r335_more (id INTEGER);"})
os.environ["PEECHA_PG_DUMP"] = "none"
import peecha.services.backup as backup_service  # noqa: E402

original = backup_service.export_backup
backup_service.export_backup = lambda *a, **k: (_ for _ in ()).throw(OSError("دیسک پر است"))
try:
    sb.apply_pending_schema_files(engine)
    no_backup = None
except sb.SchemaBackupFailed as exc:
    no_backup = str(exc)
backup_service.export_backup = original
os.environ.pop("PEECHA_PG_DUMP")
check(no_backup and "دیسک پر است" in no_backup and tracking("998_more.sql") is None,
      f"if the backup cannot be made, the upgrade does not run ({no_backup})")
check(sb.apply_pending_schema_files(engine) == ["998_more.sql"], "after fixing it, the upgrade runs")

# --- ۸: اثر انگشت: فایل منتشرشده‌ای که ویرایش شده دیده می‌شود ----------------------------------------------------------------
crlf = REAL_FILES[-2].read_text(encoding="utf-8").replace("\n", "\r\n")
use_dir({"996_extra.sql": "CREATE TABLE public.r335_extra (id INTEGER);",
         "997_ok.sql": "CREATE TABLE public.r335_ok (id INTEGER);",
         "998_more.sql": "CREATE TABLE public.r335_more (id INTEGER);"},
        changed={LAST.name: LAST.read_text(encoding="utf-8") + "\nALTER TABLE comm.distribution_runs ADD COLUMN x INT;\n",
                 REAL_FILES[-2].name: crlf})
st = sb.schema_status(engine)
check(st.changed == [LAST.name], f"an edited released file is reported; a Windows line-ending copy is not ({st.changed})")
check(st.pending == [] and st.applied >= len(REAL_FILES) and st.upgrades[0].status == "DONE", "the status lists applied files and upgrades")

# --- ۹: صفحهٔ پشتیبان دفترچهٔ ارتقا را نشان می‌دهد --------------------------------------------------------------------------
from peecha.ui.screens.system_backup import SystemBackupScreen  # noqa: E402

screen = SystemBackupScreen()
screen.refresh()
texts = [screen.upgrades_table.item(r, 4).text() for r in range(screen.upgrades_table.rowCount())]
check(screen.upgrades_table.rowCount() >= 5 and "انجام شد" in texts and any("ناموفق" in t for t in texts),
      "the backup page lists every upgrade with its result")
check("پشتیبان خودکار" in screen.upgrade_summary.text() and LAST.name in screen.upgrade_summary.text(),
      "and says where the automatic backups are and which file was edited")

# پاک‌سازی: فایل‌ها و جدول‌های آزمایشی
sql("DELETE FROM public.peecha_schema_migrations WHERE filename IN ('996_extra.sql', '997_ok.sql', '998_more.sql')")
sql("DROP TABLE IF EXISTS public.r335_extra, public.r335_ok, public.r335_more")
sb.SCHEMA_DIR = REAL_DIR
check(sb.apply_pending_schema_files(engine) == [], "back to the real release: nothing pending")
shutil.rmtree(BACKUPS, ignore_errors=True)

finish()
