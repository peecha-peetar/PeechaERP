import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r278"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prd_fixture import *  # noqa: F401,F403
import prd_fixture as fx
from sqlalchemy import text
from peecha.services import data_reset, procurement_masters, hr, commercial_pos
check = fx.check

# ۱) هر جدولِ شرکت‌محور در یکی از سه دسته است یا عمداً نگه داشته می‌شود
with new_session() as s:
    company_tables = set(s.execute(text(
        "SELECT c.table_schema||'.'||c.table_name FROM information_schema.columns c "
        "JOIN information_schema.tables t USING (table_schema, table_name) "
        "WHERE t.table_type = 'BASE TABLE' AND c.column_name = 'company_id'")).scalars())
uncovered = sorted(company_tables - data_reset.covered_tables() - data_reset.KEPT_TABLES)
check(not uncovered, f"every company table is handled by the reset tool {uncovered}")

# ۲) دادهٔ چند ماژولِ جدیدتر علاوه بر داده‌هایِ تولید/انبار/حسابداریِ فیکسچر
procurement_masters.save_branch(company_id, "BR1", "شعبهٔ مرکزی")
unit = hr.create_org_unit(company_id, "OU1", "واحد فروش", None, None)
commercial_pos.create_terminal(company_id, wh_fg, "T1", "صندوق ۱")
# سند انبار و حسابداری (رسید مواد)
fx.receive(r1, D(10), D(1000))


def remaining() -> dict:
    out = {}
    with new_session() as s:
        for table in sorted(company_tables - data_reset.KEPT_TABLES):
            n = s.execute(text(f"SELECT count(*) FROM {table} WHERE company_id = :c"), {"c": company_id}).scalar()
            if n:
                out[table] = n
    return out


before = remaining()
check(len(before) >= 12, f"fixture has data in many tables ({len(before)})")
check(fx.raises(lambda: data_reset.wipe_master_data(company_id), "اسناد"), "master data wipe refused while documents exist")
deleted = data_reset.wipe_documents(company_id)
check(deleted > 0, f"documents wiped ({deleted} rows)")
data_reset.wipe_master_data(company_id)
data_reset.wipe_settings(company_id)
left = remaining()
check(not left, f"nothing left for the company after the three wipes {left}")
with new_session() as s:
    still = s.execute(text("SELECT count(*) FROM core.companies WHERE company_id = :c"), {"c": company_id}).scalar()
    users = s.execute(text("SELECT count(*) FROM sec.user_companies WHERE company_id = :c"), {"c": company_id}).scalar()
check(still == 1 and users >= 1, "company and user access are kept")

fx.finish()
