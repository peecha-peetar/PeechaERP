"""R314: مهاجرت ۲۲۴ — اعمال، برگشت و اعمال دوباره؛ برگشت فقط اشیای افتتاحیه را برمی‌دارد و دادهٔ دیگر ماژول‌ها می‌ماند."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r314_mig"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opn_fixture import *  # noqa: F401,F403
import opn_fixture as fx

check = fx.check
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
engine = get_engine()


def scalar(sql):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def run_file(path):
    with engine.begin() as conn:
        conn.exec_driver_sql(open(path, encoding="utf-8").read().replace("BEGIN;", "").replace("COMMIT;", ""))


oc.save_settings(company_id, uid, clearing_gl.account_id, "BLOCK", None)
run = orun.create_run(company_id, uid, "M1", "آزمون مهاجرت", fy_id, balance_date, ["GL"])
oim.save_row(company_id, uid, run, "GL", {"account_code": "311", "credit": "1000"})
receive(r1, 5, 100)
docs_before = scalar("SELECT count(*) FROM inv.stock_documents")

check(scalar("SELECT count(*) FROM opn.staged_rows") == 1 and scalar(
    "SELECT count(*) FROM inv.account_mappings WHERE mapping_key='OPENING_CLEARING'") == 1, "applied: opening data and clearing mapping")
run_file(os.path.join(ROOT, "db", "rollback", "224_opening_balances_down.sql"))
check(scalar("SELECT count(*) FROM information_schema.schemata WHERE schema_name='opn'") == 0, "rollback: opn schema removed")
check("OPENING_RECEIVABLE" not in scalar("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='commercial_documents_document_type_code_check'")
      and "'OPENING'" not in scalar("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='order_transactions_txn_type_check'"),
      "rollback: original document and production transaction types restored")
check(scalar("SELECT count(*) FROM inv.account_mappings WHERE mapping_key='OPENING_CLEARING'") == 0
      and scalar("SELECT count(*) FROM inv.feature_definitions WHERE feature_code='OPN_SELF_APPROVAL'") == 0
      and scalar("SELECT count(*) FROM public.peecha_schema_migrations WHERE filename='224_opening_balances.sql'") == 0,
      "rollback: clearing mapping, switch and migration record removed")
check(scalar("SELECT count(*) FROM inv.stock_documents") == docs_before
      and scalar("SELECT count(*) FROM inv.account_mappings WHERE mapping_key='INVENTORY_ASSET'") == 1,
      "rollback keeps data of other modules")
applied = apply_pending_schema_files(engine)
check(applied == ["224_opening_balances.sql"], f"re-apply runs only 224 ({applied})")
check(scalar("SELECT count(*) FROM information_schema.tables WHERE table_schema='opn'") == 7
      and "OPENING_PAYABLE" in scalar("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='commercial_documents_document_type_code_check'"),
      "re-applied: 7 opn tables and extended checks back")
oc.save_settings(company_id, uid, clearing_gl.account_id, "BLOCK", None)
run2 = orun.create_run(company_id, uid, "M2", "پس از اعمال دوباره", fy_id, balance_date, ["GL"])
check(oim.save_row(company_id, uid, run2, "GL", {"account_code": "311", "credit": "1000"}).status == "VALID",
      "after re-apply the opening process works again")

fx.finish()
