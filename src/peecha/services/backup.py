"""پشتیبان‌گیری/بازیابی کامل دیتابیس — طبق گزارش صریح کاربر: بک‌آپ
گرفته‌شده قبل از ایجاد ماژول حقوق‌ودستمزد، جدول‌ها/فیلدهای سفارشی
اضافه‌شده بعداً را نداشت. راه‌حل: به‌جای فهرست ثابت جدول‌ها (که با هر
ماژول تازه باید دستی به‌روز شود و دقیقاً همین باگ را دوباره می‌سازد)،
ساختار *زنده*ی دیتابیس در لحظهٔ بک‌آپ با SQLAlchemy reflect می‌شود —
هر جدول یا فیلدی که این‌جا اضافه شود، خودکار در بک‌آپ بعدی می‌آید، بدون
هیچ تغییر کدی.

بازیابی هم ابتدا db/schema/*.sql را تا آخرین نسخه اجرا می‌کند (همان
مکانیزم apply_pending_schema_files) تا ساختار مقصد کاملاً به‌روز باشد،
سپس ردیف‌های فایل بک‌آپ را — فقط در ستون‌هایی که هنوز در جدول مقصد
وجود دارند — درج می‌کند؛ ستون/جدول حذف‌شده نادیده گرفته می‌شود و
خطای هر ردیف (مثلاً محدودیت NOT NULL تازه) فقط همان ردیف را متوقف
می‌کند، نه کل بازیابی را."""

from __future__ import annotations

import datetime
import decimal
import gzip
import json
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import Engine, MetaData, func, inspect, select, text
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.exc import IntegrityError

from peecha.db.schema_bootstrap import apply_pending_schema_files

# schemaهایِ داخلیِ خودِ Postgres — نباید در بک‌آپ/بازیابی دست زده شوند.
_SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "pg_toast"}

# این جدول خودِ مکانیزمِ مهاجرتِ برنامه است (کدام فایلِ db/schema/*.sql
# رویِ همین دیتابیس اجرا شده) — مالِ خودِ دیتابیسِ مقصد است، نباید از یک
# دیتابیسِ دیگر رویش بازنویسی شود.
EXCLUDED_TABLES: set[str] = {"public.peecha_schema_migrations"}

# طبقِ طراحی: به‌جایِ فهرستِ کاملِ «جدول‌هایِ تنظیمات» (که نگه‌داریِ آن با
# هر ماژولِ تازه دوباره همان باگِ گزارش‌شده را می‌سازد)، فقط جدول‌هایِ
# «تراکنشی/تاریخچه‌ای» شناخته‌شده استثنا می‌شوند؛ هر جدولِ دیگر (شاملِ هر
# جدولِ تازه‌یِ ناشناخته) پیش‌فرض «تنظیمات» درنظر گرفته می‌شود — جهتِ
# خطای امن، طرفِ «شاملِ بیشتر» نه «حذفِ داده».
TRANSACTIONAL_TABLES: set[str] = {
    "acc.journal_entries", "acc.journal_entry_lines", "acc.journal_entry_line_details",
    "hr.attendance_records", "hr.terminations",
    "payroll.bank_payment_batches", "payroll.bank_payment_lines", "payroll.deduction_entries",
    "payroll.employee_annual_tax_ledger", "payroll.employee_pay_components", "payroll.journal_entry_links",
    "payroll.loan_installments", "payroll.loans", "payroll.overtime_entries",
    "payroll.payslip_lines", "payroll.payslips", "payroll.runs",
    "treasury.check_stage_events", "treasury.issued_checks", "treasury.received_checks",
    "wf.cartable_actions", "wf.cartable_item_steps", "wf.cartable_items",
    "doc.attachments",
    "audit.activity_log",
    "sec.role_field_permissions_history", "sec.role_form_permissions_history",
    "sec.role_menu_permissions_history", "sec.user_module_roles_history", "sec.user_roles_history",
}


@dataclass
class BackupTableInfo:
    schema: str
    name: str
    full_name: str
    row_count: int
    is_setup: bool


def _full_name(table) -> str:
    return f"{table.schema}.{table.name}" if table.schema else table.name


def _reflect(engine: Engine) -> MetaData:
    """طبق طراحی: schemaهای برنامه (core/sec/acc/hr/payroll/treasury/wf/doc/
    audit/public و هر schemaی تازه‌ای که بعداً اضافه شود) به‌صورت پویا از
    خود دیتابیس پرسیده می‌شوند — reflect بدون schema=، فقط schemaی
    پیش‌فرض اتصال (public) را می‌بیند و اکثر جدول‌های برنامه را که در
    schemaهای دیگرند نادیده می‌گیرد."""
    metadata = MetaData()
    inspector = inspect(engine)
    for schema_name in inspector.get_schema_names():
        if schema_name in _SYSTEM_SCHEMAS:
            continue
        metadata.reflect(bind=engine, schema=schema_name)
    return metadata


def list_backup_tables(engine: Engine) -> list[BackupTableInfo]:
    metadata = _reflect(engine)
    result: list[BackupTableInfo] = []
    with engine.connect() as conn:
        for table in metadata.sorted_tables:
            full_name = _full_name(table)
            if full_name in EXCLUDED_TABLES:
                continue
            count = conn.execute(select(func.count()).select_from(table)).scalar_one()
            result.append(
                BackupTableInfo(
                    schema=table.schema or "public",
                    name=table.name,
                    full_name=full_name,
                    row_count=count,
                    is_setup=full_name not in TRANSACTIONAL_TABLES,
                )
            )
    return sorted(result, key=lambda t: (t.schema, t.name))


def _serialize_value(value):
    if isinstance(value, decimal.Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, datetime.datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, datetime.date):
        return {"__date__": value.isoformat()}
    if isinstance(value, datetime.time):
        return {"__time__": value.isoformat()}
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes_hex__": value.hex()}
    return value


def _deserialize_value(value):
    if isinstance(value, dict):
        if "__decimal__" in value:
            return decimal.Decimal(value["__decimal__"])
        if "__datetime__" in value:
            return datetime.datetime.fromisoformat(value["__datetime__"])
        if "__date__" in value:
            return datetime.date.fromisoformat(value["__date__"])
        if "__time__" in value:
            return datetime.time.fromisoformat(value["__time__"])
        if "__bytes_hex__" in value:
            return bytes.fromhex(value["__bytes_hex__"])
    return value


def _missing_links(conn, table, raw_row: dict, cache: dict) -> dict[str, str]:
    """R339: پیوندهای ردیف که ردیف والدشان هنوز در مقصد نیست: {ستون: جدول والد}."""
    gaps: dict[str, str] = {}
    for fk in table.foreign_key_constraints:
        pairs = [(e.parent.name, e.column.name) for e in fk.elements]
        values = [raw_row.get(local) for local, _remote in pairs]
        if any(v is None for v in values):
            continue
        ref = fk.referred_table
        quoted = f'"{ref.schema}"."{ref.name}"' if ref.schema else f'"{ref.name}"'
        where = " AND ".join(f'"{remote}" = :v_{i}' for i, (_local, remote) in enumerate(pairs))
        key = (quoted, where, json.dumps(values, sort_keys=True, default=str))
        if key not in cache:
            params = {f"v_{i}": _deserialize_value(v) for i, v in enumerate(values)}
            cache[key] = conn.execute(text(f"SELECT 1 FROM {quoted} WHERE {where} LIMIT 1"), params).first() is not None
        if not cache[key]:
            gaps.update({local: _full_name(ref) for local, _remote in pairs})
    return gaps


def _open(path: str, mode: str):
    return gzip.open(path, mode, encoding="utf-8") if path.lower().endswith(".gz") else open(path, mode, encoding="utf-8")


def export_backup(engine: Engine, path: str, selected_full_names: set[str] | None = None) -> dict:
    """selected_full_names=None یعنی همهٔ جدول‌ها (به‌جز EXCLUDED_TABLES)."""
    metadata = _reflect(engine)
    ordered = [t for t in metadata.sorted_tables if _full_name(t) not in EXCLUDED_TABLES]
    if selected_full_names is not None:
        ordered = [t for t in ordered if _full_name(t) in selected_full_names]

    manifest_tables: list[dict] = []
    payload_data: dict[str, list[dict]] = {}
    with engine.connect() as conn:
        for table in ordered:
            full_name = _full_name(table)
            rows = conn.execute(select(table)).mappings().all()
            payload_data[full_name] = [{col: _serialize_value(row[col]) for col in row.keys()} for row in rows]
            manifest_tables.append({"name": full_name, "row_count": len(rows)})

    manifest = {"exported_at": datetime.datetime.now().isoformat(), "tables": manifest_tables}
    with _open(path, "wt") as f:
        json.dump({"manifest": manifest, "data": payload_data}, f, ensure_ascii=False)
    return manifest


@dataclass
class RestoreTableResult:
    full_name: str
    inserted: int
    skipped_existing: int
    errors: int
    error_samples: list[str]


@dataclass
class RestoreReport:
    tables: list[RestoreTableResult]
    skipped_unknown_tables: list[str]


def import_backup(engine: Engine, path: str) -> RestoreReport:
    # طبقِ طراحی: اول ساختارِ مقصد را کاملاً به‌روز می‌کنیم — همان
    # مکانیزمِ استارت‌آپِ برنامه — تا بازیابی همیشه رویِ آخرین نسخهٔ
    # ساختار انجام شود، صرفِ‌نظر از اینکه فایلِ بک‌آپ چه زمانی گرفته شده.
    apply_pending_schema_files(engine, source="restore", backup=False)

    with _open(path, "rt") as f:
        payload = json.load(f)
    data: dict[str, list[dict]] = payload["data"]

    metadata = _reflect(engine)
    tables_by_name = {_full_name(t): t for t in metadata.sorted_tables}

    results: list[RestoreTableResult] = []
    skipped_unknown = [name for name in data if name not in tables_by_name]

    with engine.begin() as conn:
        jobs: list[SimpleNamespace] = []
        for table in metadata.sorted_tables:
            full_name = _full_name(table)
            if full_name not in data or full_name in EXCLUDED_TABLES:
                continue
            # R339: ستون محاسبه‌شده (GENERATED ALWAYS AS ... STORED) را خود دیتابیس می‌سازد و مقدار صریح نمی‌پذیرد؛
            # بدون این، ردیف‌های سند حسابداری، کارتکس، سندهای بازرگانی و... اصلاً بازیابی نمی‌شدند
            target_columns = {c.name for c in table.columns if c.computed is None}
            # طبقِ نیازِ فنی: ستون‌هایِ GENERATED ALWAYS AS IDENTITY (که این
            # پروژه برایِ اکثرِ کلیدهایِ اصلی استفاده می‌کند) بدونِ
            # OVERRIDING SYSTEM VALUE اجازه‌یِ مقدارِ صریح نمی‌دهند — بدونِ
            # این، بازیابی همیشه با «cannot insert a non-DEFAULT value»
            # شکست می‌خورد، دقیقاً همان چیزی که این تابع باید حلش کند.
            always_identity_cols = {c.name for c in table.columns if c.identity is not None and c.identity.always}
            # طبقِ نیازِ فنی: ستون‌هایِ JSON/JSONB (مثلِ acc.detail_accounts.
            # extra_fields) وقتی INSERT با text() خام (نه Coreِ insert())
            # نوشته می‌شود، psycopg2 نمی‌داند یک dictِ پایتونی را چطور به
            # پارامتر تبدیل کند — باید صریحاً به رشته‌یِ JSON سریالایز و در
            # خودِ SQL با ::jsonb/::json کست شود.
            json_columns = {c.name for c in table.columns if isinstance(c.type, (JSON, JSONB))}
            quoted_table = f'"{table.schema}"."{table.name}"' if table.schema else f'"{table.name}"'

            # R339: مقادیر همین جدول به تابع بسته می‌شوند، چون درج در دورهای بعدی (بیرون از این حلقه) هم انجام می‌شود
            def _try_insert_row(raw_row: dict, target_columns=target_columns, always_identity_cols=always_identity_cols,
                                json_columns=json_columns, quoted_table=quoted_table) -> tuple[bool, bool, str | None]:
                """یک ردیف را درج می‌کند. خروجی: (موفق؟, خطا_قابل‌رفع‌بعدی؟ (یعنی
                IntegrityError ممکن‌است-به‌خاطر-ترتیب باشد, پیام خطا)."""
                row = {k: _deserialize_value(v) for k, v in raw_row.items() if k in target_columns}
                if not row:
                    return True, False, None
                needs_override = bool(set(row) & always_identity_cols)
                col_list = ", ".join(f'"{c}"' for c in row)
                bind_params = dict(row)
                placeholder_parts = []
                for c in row:
                    if c in json_columns and row[c] is not None:
                        # طبقِ یک نکته‌یِ فنیِ شناخته‌شده: نوشتنِ `:col::jsonb`
                        # (دو نقطه‌یِ پشتِ‌سرهم بلافاصله بعدِ نامِ پارامتر) با
                        # تشخیصِ توکنِ bind parameter در SQLAlchemyِ text()
                        # تداخل می‌کند؛ CAST صریح این ابهام را کاملاً حذف می‌کند.
                        placeholder_parts.append(f"CAST(:{c} AS jsonb)")
                        bind_params[c] = json.dumps(row[c])
                    else:
                        placeholder_parts.append(f":{c}")
                placeholders = ", ".join(placeholder_parts)
                override_clause = " OVERRIDING SYSTEM VALUE" if needs_override else ""
                stmt = text(f'INSERT INTO {quoted_table} ({col_list}){override_clause} VALUES ({placeholders})')
                savepoint = conn.begin_nested()
                try:
                    conn.execute(stmt, bind_params)
                    savepoint.commit()
                    return True, False, None
                except IntegrityError as exc:
                    savepoint.rollback()
                    return False, True, str(exc)[:200]
                except Exception as exc:  # noqa: BLE001 - هر خطایِ ردیف باید فقط همان ردیف را متوقف کند
                    savepoint.rollback()
                    return False, False, str(exc)[:200]

            # طبقِ رفعِ باگِ صریح («بعدِ بازیابیِ بک‌آپ، سطوح و تعدادِ سطوحِ
            # حساب‌هایِ تفصیلی به‌هم ریخته»): جدول‌هایی مثلِ acc.chart_of_accounts
            # و acc.detail_accounts خودشان به خودشان ارجاعِ سلسله‌مراتبی دارند
            # (parent_account_id/parent_detail_account_id). ردیف‌های exportشده
            # بدونِ ORDER BY خوانده می‌شوند، پس ترتیبِ آن‌ها تضمین‌شده نیست —
            # اگر یک ردیفِ فرزند پیش از والدش درج شود، به‌خاطرِ نقضِ کلیدِ
            # خارجی با IntegrityError شکست می‌خورد و قبلاً به‌عنوانِ «ردیفِ
            # تکراری/نامعتبر» به‌سادگی نادیده گرفته می‌شد — یعنی آن حسابِ
            # تفصیلی/حسابِ حسابداری کلاً از بازیابی جا می‌ماند. راه‌حل: هر
            # ردیفی که با IntegrityError شکست بخورد (که می‌تواند به‌خاطرِ
            # ترتیب باشد، نه لزوماً نامعتبربودنِ خودِ ردیف)، در پاس‌هایِ بعدی
            # دوباره امتحان می‌شود؛ با هر پاسِ موفق، ردیف‌هایِ والدِ تازه‌درج‌شده
            # فرزندانشان را در پاسِ بعدی قابلِ‌درج می‌کنند. وقتی یک پاسِ کامل
            # هیچ پیشرفتی نداشته باشد (یعنی خطا واقعاً به‌خاطرِ ترتیب نبوده)،
            # باقیمانده قطعی شکست‌خورده/ردشده ثبت می‌شود.
            jobs.append(SimpleNamespace(
                full_name=full_name, insert=_try_insert_row, pending=list(data[full_name]), inserted=0, errors=0,
                error_samples=[], last_errors={}, quoted_table=quoted_table, pk=[c.name for c in table.primary_key.columns],
                table=table))

        # R339: همین تکرار برای کل جدول‌ها: جدول‌های با کلید خارجی چرخه‌ای (مثلاً انبار ↔ محل پیش‌فرض) ترتیب مطمئنی ندارند و
        # ردیفی که والدش در جدول بعدی بود، قبلاً بی‌صدا «ردشده» می‌ماند (انبارها، دستور تولید، کارتکس، ...).
        def _run_passes() -> None:
            progressed = True
            while progressed:
                progressed = False
                for job in jobs:
                    while job.pending:
                        next_pending: list[dict] = []
                        table_progress = False
                        for raw_row in job.pending:
                            ok, retryable, message = job.insert(raw_row)
                            if ok:
                                job.inserted += 1
                                table_progress = True
                            elif retryable:
                                next_pending.append(raw_row)
                                job.last_errors[id(raw_row)] = message
                            else:
                                job.errors += 1
                                if len(job.error_samples) < 5 and message:
                                    job.error_samples.append(message)
                        job.pending = next_pending
                        if not table_progress:
                            break
                        progressed = True

        _run_passes()
        # R339: چرخهٔ واقعی (انبار ← محل پیش‌فرض ← همان انبار): فقط ردیف‌های خود چرخه، با خالی‌کردن پیوند اختیاری‌ای که
        # والدش هنوز نیامده، درج می‌شوند؛ بقیه پشتشان می‌آیند و در پایان همان پیوندها روی ردیف نوشته می‌شوند. ردیفی که
        # فقط منتظر والدش است دست نمی‌خورد، چون بعضی جدول‌ها (مثل تراکنش تولید) اصلاح بعدی را نمی‌پذیرند.
        deferred: list[tuple] = []
        while True:
            gaps_of: dict[int, dict[str, str]] = {}
            waits: dict[str, set[str]] = {}
            cache: dict = {}
            for job in jobs:
                for raw_row in job.pending:
                    gaps = _missing_links(conn, job.table, raw_row, cache)
                    if gaps:
                        gaps_of[id(raw_row)] = gaps
                        waits.setdefault(job.full_name, set()).update(gaps.values())
            reach: dict[str, set[str]] = {}
            for start in waits:
                seen, stack = set(), [start]
                while stack:
                    for nxt in waits.get(stack.pop(), ()):
                        if nxt not in seen:
                            seen.add(nxt)
                            stack.append(nxt)
                reach[start] = seen
            picked = False
            for job in jobs:
                if job.full_name not in reach.get(job.full_name, ()) or not job.pk:
                    continue
                cycle = {name for name in reach[job.full_name] if job.full_name in reach.get(name, ())}
                nullable = {c.name for c in job.table.columns if c.nullable and c.computed is None}
                still: list[dict] = []
                for raw_row in job.pending:
                    gaps = gaps_of.get(id(raw_row))
                    ok = False
                    if gaps and set(gaps) <= nullable and set(gaps.values()) <= cycle:
                        ok, _retryable, _message = job.insert({**raw_row, **{c: None for c in gaps}})
                    if ok:
                        job.inserted += 1
                        deferred.append((job, raw_row, {c: raw_row[c] for c in gaps}))
                        picked = True
                    else:
                        still.append(raw_row)
                job.pending = still
                if picked:
                    break
            if not picked:
                break
            _run_passes()
        if deferred:
            for job, raw_row, links in deferred:
                sets = ", ".join(f'"{c}" = :v_{i}' for i, c in enumerate(links))
                where = " AND ".join(f'"{c}" = :k_{i}' for i, c in enumerate(job.pk))
                params = {f"v_{i}": _deserialize_value(v) for i, v in enumerate(links.values())}
                params.update({f"k_{i}": _deserialize_value(raw_row[c]) for i, c in enumerate(job.pk)})
                savepoint = conn.begin_nested()
                try:
                    conn.execute(text(f"UPDATE {job.quoted_table} SET {sets} WHERE {where}"), params)
                    savepoint.commit()
                except Exception as exc:  # noqa: BLE001 - فقط همین پیوند برقرار نمی‌شود
                    savepoint.rollback()
                    job.errors += 1
                    if len(job.error_samples) < 5:
                        job.error_samples.append(f"پیوند ردیف برقرار نشد: {str(exc)[:160]}")
        for job in jobs:
            for raw_row in job.pending:
                message = job.last_errors.get(id(raw_row))
                if len(job.error_samples) < 5 and message:
                    job.error_samples.append(message)
            results.append(RestoreTableResult(job.full_name, job.inserted, len(job.pending), job.errors, job.error_samples))

        # طبقِ نیازِ فنی: بعدِ درجِ دستیِ مقادیرِ شناسه، دنباله‌یِ (sequence)
        # ستون‌هایِ identity باید هم‌گام شود، وگرنه اولین درجِ خودکارِ بعدی
        # (بدونِ مقدارِ صریح) با شناسه‌یِ تکراری برخورد می‌کند.
        for table in metadata.sorted_tables:
            full_name = _full_name(table)
            if full_name not in data:
                continue
            quoted_table = f'"{table.schema}"."{table.name}"' if table.schema else f'"{table.name}"'
            for col in table.columns:
                if not col.primary_key:
                    continue
                seq_name = conn.execute(
                    text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": quoted_table, "c": col.name}
                ).scalar()
                if not seq_name:
                    continue
                conn.execute(
                    text(f'SELECT setval(:seq, COALESCE((SELECT MAX("{col.name}") FROM {quoted_table}), 1))'),
                    {"seq": seq_name},
                )

    return RestoreReport(tables=results, skipped_unknown_tables=skipped_unknown)
