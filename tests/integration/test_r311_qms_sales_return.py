"""R311: بازرسی مرجوعی فروش — کلید «کنترل کیفیت مرجوعی فروش»: کالای برگشتی مشتری تا بازرسی آزاد نمی‌شود، مقدار معیوب به
قرنطینه می‌رود، عدم‌انطباق با منبع «مرجوعی مشتری» ساخته می‌شود و امتیاز تامین‌کننده از آن اثر نمی‌گیرد."""
import os, sys
os.environ["PEECHA_DB_NAME"] = "peecha_test_r311c"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crm_fixture import *  # noqa: F401,F403
import crm_fixture as fx
from sqlalchemy import func
from peecha.services import quality_control as qc
from peecha.services import stock_controls as sc
from peecha.services.qms import ncr, queries, scoring
from peecha.db.models.inventory import QcInspection, StockBalance
check, raises = fx.check, fx.raises

whq = locations_service.create_warehouse(company_id, "WH-Q", "قرنطینه", locations_service.WarehouseFields(warehouse_type_code="QUARANTINE"))
switch = lambda code, on=True: engine_service.set_feature_enabled(company_id, code, on)  # noqa: E731
HF = lambda cp: documents_service.DocumentHeaderFields(counterparty_detail_account_id=cp, currency_id=company.base_currency_id,  # noqa: E731
                                                      warehouse_id=warehouse_id, channel_code=channel_code)


def stock(item, warehouse, field="quantity_on_hand"):
    with new_session() as s:
        return D(s.scalar(select(func.coalesce(func.sum(getattr(StockBalance, field)), 0)).where(
            StockBalance.item_id == item, StockBalance.warehouse_id == warehouse)) or 0)


def sales_return(qty, customer=cust_a):
    d = documents_service.create_document(company_id, uid, "SALES_RETURN", today, HF(customer))
    documents_service.add_line(d, company_id, item_a, pcs, D(qty), D(qty), unit_price=D(50000))
    documents_service.confirm_document(d, company_id, uid)
    documents_service.post_document(d, company_id, uid)
    return d


invoice(cust_a, 50000)
before = stock(item_a, warehouse_id)
switch(sc.RESERVATION)
switch(sc.QC_HOLD)
sales_return(1)
check(qc.list_pending(company_id) == [] and stock(item_a, warehouse_id) == before + 1,
      "switch off: customer return is free stock (previous behaviour)")

switch(sc.QC_SALES_RETURN)
r2 = sales_return(3)
pend = qc.list_pending(company_id)
check(len(pend) == 1 and pend[0].stage_code == "SALES_RETURN" and pend[0].quantity == 3 and pend[0].party_name == "فروشگاه الف"
      and stock(item_a, warehouse_id, "quantity_reserved") == 3, "switch on: returned goods held for inspection")
check(raises(lambda: qc.record_result(company_id, pend[0].line_id, uid, accepted=D(2), rejected=D(2)), "برابر"),
      "return inspection cannot exceed the returned quantity")
i1 = qc.record_result(company_id, pend[0].line_id, uid, accepted=D(2), rejected=D(1), notes="یک عدد شکسته")
with new_session() as s:
    row = s.get(QcInspection, i1)
check(row.stage_code == "SALES_RETURN" and row.status_code == "RECORDED", "recorded as a sales-return inspection")
qc.approve(company_id, i1, visitor.user_id, whq)
check(stock(item_a, whq) == 1 and stock(item_a, warehouse_id, "quantity_reserved") == 0 and qc.list_pending(company_id) == [],
      "approved: 2 back to sellable stock, 1 to quarantine")
n = [x for x in ncr.list_ncrs(company_id) if x.qc_inspection_id == i1]
with new_session() as s:
    from peecha.db.models.quality import Nonconformance
    nrow = s.get(Nonconformance, n[0].ncr_id) if n else None
check(len(n) == 1 and n[0].source_code == "SALES_RETURN" and nrow.customer_detail_account_id == cust_a
      and nrow.supplier_detail_account_id is None, "customer-return NCR linked to the customer, not a supplier")
check(scoring.supplier_scores(company_id) == [], "sales-return inspections do not count in supplier scores")
detail = queries.inspection_detail(company_id, i1)
check(detail.header.stage_label == "مرجوعی فروش" and "فروشگاه الف" in detail.header.party_label
      and [h.changes.get("operation") for h in detail.history] == ["QC_RECORD", "QC_APPROVE"], "detail and decision history")

finish()
