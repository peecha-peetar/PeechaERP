"""کالای در جریان ساخت افتتاحیه (R314، تصمیم کاربر): برای هر دستور باز سیستم قبلی، دستور تولید با سرویس رسمی و فقط
برای مقدار باقی‌مانده ساخته می‌شود و هزینهٔ انباشته با تراکنش OPENING به WIP همان دستور می‌رود (بدهکار WIP، بستانکار
حساب واسط). مواد مصرف‌شدهٔ قبلی دوباره حواله نمی‌شود؛ دستور در وضعیت پیش‌نویس می‌ماند تا برنامه‌ریز آن را صادر کند.
"""

from __future__ import annotations

import datetime

from peecha.services.opening import common as c


def _date(value) -> datetime.date | None:
    if not value:
        return None
    return value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value)[:10])


def post(company_id: int, user_id: int, run, step, rows_of) -> list:
    from peecha.db.base import new_session
    from peecha.services import detail_dimensions as dims
    from peecha.services import journal_entries as je_service
    from peecha.services.production import orders as po

    clearing = c.clearing_account_id(company_id)
    cc_type = dims.get_specialized_dimension_type_id(company_id, dims.COST_CENTER_CODE)
    pj_type = dims.get_specialized_dimension_type_id(company_id, dims.PROJECT_CODE)
    with new_session() as session:
        rows = [(r.row_id, dict(r.resolved)) for r in rows_of(session, run.run_id, "WIP")]
    outcomes = []
    for rid, res in rows:
        def work(session, rid=rid, res=res):
            from peecha.services import inventory_engine as engine

            fields = po.OrderFields(
                item_id=int(res["item_id"]), planned_qty=c.dec(res["remaining_qty"]),
                start_date=_date(res.get("start_date")) or run.go_live_date,
                due_date=_date(res.get("due_date")), material_warehouse_id=res.get("material_warehouse_id"),
                fg_warehouse_id=res.get("fg_warehouse_id"), cost_center_detail_account_id=res.get("cost_center_id"),
                project_detail_account_id=res.get("project_id"),
                notes=f"دستور افتتاحیه {run.code} — شمارهٔ سیستم قبلی {res.get('legacy_order_no')}")
            po._apply_defaults(session, company_id, fields)
            if fields.due_date < fields.start_date:
                fields.due_date = fields.start_date
            po._validate(session, company_id, fields)
            order = po._insert_order(session, company_id, user_id, fields, f"OPN{run.run_id}-WIP{rid}")
            amount = c.money(res["wip_amount"])
            je = None
            if amount:
                details = {}
                if order.cost_center_detail_account_id:
                    details[cc_type] = order.cost_center_detail_account_id
                if order.project_detail_account_id:
                    details[pj_type] = order.project_detail_account_id
                wip_account = engine._resolve_role_account(session, company_id, "PRODUCTION_WIP")
                je = je_service.create_journal_entry(
                    company_id, user_id, run.go_live_date, f"{order.order_code} — کالای در جریان ساخت افتتاحیه", [
                        je_service.LineInput(account_id=wip_account, description=f"WIP افتتاحیه {order.order_code}",
                                             debit=amount, credit=c.ZERO, details=details),
                        je_service.LineInput(account_id=clearing, description="کالای در جریان ساخت افتتاحیه — طرف مقابل",
                                             debit=c.ZERO, credit=amount)],
                    alternative_number=f"OPN-{run.code}", entry_type_code="OPENING", session=session).journal_entry_id
            po.record(session, order, "OPENING", run.go_live_date, user_id, item_id=order.item_id, amount=amount,
                      wip_delta=amount, journal_entry_id=je, reason=f"افتتاحیه {run.code}",
                      details={"legacy_order_no": res.get("legacy_order_no")}, key=f"OPN{run.run_id}-WIP{rid}")
            return {"target_type": "PRODUCTION_ORDER", "target_id": order.order_id, "journal_entry_id": je, "amount": amount}
        outcomes.append(step(run.run_id, "WIP", f"WIP:{rid}", user_id, [rid], work))
    return outcomes
