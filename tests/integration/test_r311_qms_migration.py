"""R311: مهاجرت ۲۲۱ — اعمال، برگشت و اعمال دوباره روی دیتابیس دارای بازرسی قدیمی؛ پرشدن مقادیر بازرسی‌های قبلی
(مقدار تحت کنترل، پذیرفته، تصمیم، تأییدکننده) و حفظ بازرسی‌ها پس از برگشت."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r311d"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import text, update
from peecha.services import inventory_documents as inv_docs
from peecha.services import quality_control as qc
from peecha.services import stock_controls as sc
from peecha.db.models.inventory import Item
check = fx.check

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
g_l = A("2", "بدهی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False)
k_l = A("21", "پرداختنی‌ها", "CREDIT", "LIABILITY", "PERMANENT", False, g_l.account_id)
ap_gl = A("2101", "پرداختنی تامین‌کنندگان", "CREDIT", "LIABILITY", "PERMANENT", True, k_l.account_id)
engine_service.set_account_mapping(company_id, "SUPPLIER_PAYABLE", ap_gl.account_id)
sup = dimensions_service.create_supplier(company_id, "S1", "تامین‌کننده")
whq = locations_service.create_warehouse(company_id, "WH-Q", "قرنطینه", locations_service.WarehouseFields(warehouse_type_code="QUARANTINE"))
with new_session() as s:
    s.execute(update(Item).where(Item.item_id == item_b).values(requires_qc=True))
    s.commit()
engine_service.set_feature_enabled(company_id, sc.RESERVATION, True)
engine_service.set_feature_enabled(company_id, sc.QC_HOLD, True)


def receipt(qty):
    d = inv_docs.create_stock_document(company_id, uid, "RECEIPT", today, inv_docs.DocumentHeaderFields(
        destination_warehouse_id=warehouse_id, counterparty_detail_account_id=sup))
    line = inv_docs.add_line(d, company_id, inv_docs.LineFields(item_id=item_b, uom_id=pcs, quantity=D(qty), quantity_base=D(qty),
                                                                unit_cost=D(100)))
    inv_docs.confirm_stock_document(d, company_id)
    inv_docs.post_stock_document(d, company_id, uid)
    return line


l1 = receipt(10)
qc.inspect(company_id, l1, uid, D(3), whq)
l2 = receipt(4)
qc.inspect(company_id, l2, uid)
engine = get_engine()


def scalar(sql):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def run_file(path):
    with engine.begin() as conn:
        conn.exec_driver_sql(open(path, encoding="utf-8").read().replace("BEGIN;", "").replace("COMMIT;", ""))


check(scalar("SELECT count(*) FROM information_schema.schemata WHERE schema_name='qms'") == 1, "applied: qms schema exists")
run_file(os.path.join(ROOT, "db", "rollback", "221_qms_down.sql"))
check(scalar("SELECT count(*) FROM information_schema.schemata WHERE schema_name='qms'") == 0
      and scalar("SELECT count(*) FROM information_schema.columns WHERE table_schema='inv' AND table_name='qc_inspections' "
                 "AND column_name='status_code'") == 0, "rollback: qms schema and new columns removed")
check(scalar("SELECT count(*) FROM inv.qc_inspections") == 2
      and scalar("SELECT count(*) FROM inv.feature_definitions WHERE feature_code LIKE 'QC\\_%'") == 0
      and scalar("SELECT count(*) FROM public.peecha_schema_migrations WHERE filename='221_qms.sql'") == 0,
      "rollback keeps the old inspections, removes switches and the migration record")
applied = apply_pending_schema_files(engine)
check(applied == ["221_qms.sql"], f"re-apply runs only 221 ({applied})")
rows = {r[0]: r[1:] for r in engine.connect().execute(text(
    "SELECT stock_document_line_id, lot_quantity, accepted_quantity, disposition_code, status_code, stage_code, "
    "approved_by_user_id IS NOT NULL FROM inv.qc_inspections"))}
check(rows[l1] == (D(10), D(7), "PARTIAL", "APPROVED", "RECEIPT", True) and rows[l2] == (D(4), D(4), "ACCEPT", "APPROVED", "RECEIPT", True),
      f"old inspections backfilled (lot, accepted, decision, approver) {rows}")
check(scalar("SELECT count(*) FROM inv.feature_definitions WHERE category='QUALITY' AND feature_code LIKE 'QC\\_%'") == 5,
      "five quality switches back")
try:
    with engine.begin() as conn:
        conn.execute(text("UPDATE inv.qc_inspections SET rejected_quantity = 0 WHERE stock_document_line_id = :l"), {"l": l1})
    locked = False
except Exception as exc:  # noqa: BLE001
    locked = "QC_LOCKED" in str(exc)
check(locked, "backfilled approved inspections are locked")
try:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO inv.qc_inspections (company_id, stock_document_line_id, inspected_by_user_id, result_code, "
                          "rejected_quantity, lot_quantity, accepted_quantity, pending_quantity, status_code) "
                          "VALUES (:c, :l, :u, 'PARTIAL', 6, 10, 6, 0, 'RECORDED')"), {"c": company_id, "l": l1, "u": uid})
    over = False
except Exception as exc:  # noqa: BLE001
    over = "ck_inv_qc_inspections_quantities" in str(exc)
check(over, "database refuses accepted + rejected + pending above the lot")
check(apply_pending_schema_files(engine) == [], "nothing pending on a second run (idempotent bootstrap)")

finish()
