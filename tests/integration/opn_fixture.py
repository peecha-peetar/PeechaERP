"""Shared setup for R314 opening-balance tests (on top of prd_fixture). Import after setting PEECHA_DB_NAME."""
import csv
import datetime

from prd_fixture import *  # noqa: F401,F403
import prd_fixture as _p

from peecha.db.models.accounting import FiscalYear
from peecha.db.models.opening import StagedRow
from peecha.services import roles as roles_service
from peecha.services import users as users_service
from peecha.services.opening import common as oc
from peecha.services.opening import importer as oim
from peecha.services.opening import roles_setup as oroles
from peecha.services.opening import runs as orun

check, raises, D = _p.check, _p.raises, _p.D
company_id, uid, today = _p.company_id, _p.uid, _p.today
A, dims = _p.A, _p.dimensions_service

person_type = dims.get_person_dimension_type_id(company_id)
cc_type = dims.get_specialized_dimension_type_id(company_id, dims.COST_CENTER_CODE)

k_cash = A("11", "موجودی نقد", "DEBIT", "ASSET", "PERMANENT", False, _p.g1.account_id)
cash_gl = A("111", "صندوق", "DEBIT", "ASSET", "PERMANENT", True, k_cash.account_id)
k_ar = A("13", "دریافتنی‌ها", "DEBIT", "ASSET", "PERMANENT", False, _p.g1.account_id)
ar_gl = A("131", "دریافتنی تجاری", "DEBIT", "ASSET", "PERMANENT", True, k_ar.account_id)
k_fa = A("14", "دارایی‌های ثابت", "DEBIT", "ASSET", "PERMANENT", False, _p.g1.account_id)
fa_cost_gl = A("141", "بهای دارایی ثابت", "DEBIT", "ASSET", "PERMANENT", True, k_fa.account_id)
fa_dep_gl = A("142", "استهلاک انباشته", "CREDIT", "ASSET", "PERMANENT", True, k_fa.account_id)
g_eq = A("3", "حقوق صاحبان سهام", "CREDIT", "EQUITY", "PERMANENT", False)
k_cap = A("31", "سرمایه", "CREDIT", "EQUITY", "PERMANENT", False, g_eq.account_id)
capital_gl = A("311", "سرمایهٔ ثبت‌شده", "CREDIT", "EQUITY", "PERMANENT", True, k_cap.account_id)
k_clr = A("39", "حساب‌های انتقالی", "CREDIT", "EQUITY", "PERMANENT", False, g_eq.account_id)
clearing_gl = A("391", "حساب واسط افتتاحیه", "CREDIT", "EQUITY", "PERMANENT", True, k_clr.account_id)
diff_gl = A("392", "اختلاف افتتاحیه", "CREDIT", "EQUITY", "PERMANENT", True, k_clr.account_id)
k_dep = A("53", "هزینهٔ استهلاک", "DEBIT", "EXPENSE", "TEMPORARY", False, _p.g3.account_id)
dep_exp_gl = A("531", "هزینهٔ استهلاک", "DEBIT", "EXPENSE", "TEMPORARY", True, k_dep.account_id)
for acc in (ar_gl, _p.ap_gl):
    dims.set_account_dimension_types(acc.account_id, company_id, [person_type])
_p.engine_service.set_account_mapping(company_id, "CUSTOMER_RECEIVABLE", ar_gl.account_id)

cust1 = dims.create_customer(company_id, "C1", "مشتری یک")
cust2 = dims.create_customer(company_id, "C2", "مشتری دو")
cc_prod = dims.create_detail_account(company_id, cc_type, "CC1", "تولید").detail_account_id

with _p.new_session() as _s:
    fy = _s.scalar(_p.select(FiscalYear).where(FiscalYear.company_id == company_id))
    fy_id, fy_start, fy_end = fy.fiscal_year_id, fy.start_date, fy.end_date
balance_date = fy_start - datetime.timedelta(days=1)
go_live = fy_start

roles_service.ensure_catalog()
roles = oroles.ensure_role_templates(company_id)


def user(name, *role_codes):
    u = users_service.create_user(name, name, "secret123", None, None, False, [company_id], company_id).user_id
    for code in role_codes:
        roles_service.set_user_role(u, roles[code], company_id, True)
    return u


def toggle(code, on=True):
    _p.engine_service.set_feature_enabled(company_id, code, on)


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return path


def write_xlsx(path, header, rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(list(r))
    wb.save(path)
    return path


def rows_of(run_id, module):
    with _p.new_session() as s:
        return list(s.scalars(_p.select(StagedRow).where(StagedRow.run_id == run_id, StagedRow.module_code == module)
                              .order_by(StagedRow.row_id)))


def module_status(run_id, module):
    return next(m.status_code for m in orun.get_run(company_id, run_id).modules if m.module_code == module)


def finish():
    _p.finish()
