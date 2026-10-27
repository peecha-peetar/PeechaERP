"""R344: ردپای خودکار تغییر جدول‌های حساس در audit.activity_log.

کاربر، نقش، مجوز، شرکت، سال و دورهٔ مالی، تنظیم حساب‌ها، قابلیت‌ها، شماره‌گذاری و تنظیمات حقوق
بدون دست‌زدن به سرویس‌ها ثبت می‌شوند: در همان flush و تراکنش عملیات (اگر عملیات برگردد، ردپا هم
ثبت نمی‌شود). رمز و هیچ دادهٔ دودویی ثبت نمی‌شود؛ فقط «رمز تغییر کرد».
حذف گروهی با query().delete() از ORM عبور نمی‌کند؛ برای جدول‌های دسترسی همان تاریخچهٔ تریگری
sec.*_history (002_security_rbac.sql) پوشش می‌دهد."""

from __future__ import annotations

import datetime
import decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

# جدول ← (نوع موجودیت، ستون شناسه)
_TRACKED: dict[str, tuple[str, str]] = {
    "sec.users": ("User", "user_id"),
    "sec.roles": ("Role", "role_id"),
    "sec.role_form_permissions": ("RoleFormPermission", "role_id"),
    "sec.user_roles": ("UserRole", "user_id"),
    "sec.user_module_roles": ("UserModuleRole", "user_id"),
    "core.companies": ("Company", "company_id"),
    "core.company_currencies": ("CompanyCurrency", "company_id"),
    "acc.fiscal_years": ("FiscalYear", "fiscal_year_id"),
    "acc.fiscal_periods": ("FiscalPeriod", "fiscal_period_id"),
    "acc.company_accounting_settings": ("AccountingSettings", "company_id"),
    "acc.chart_of_account_level_config": ("AccountLevelConfig", "company_id"),
    "comm.account_mappings": ("AccountMapping", "company_id"),
    "comm.company_features": ("CompanyFeature", "company_id"),
    "comm.document_numbering_sequences": ("NumberingSequence", "company_id"),
    "payroll.company_settings": ("PayrollSettings", "company_id"),
    "payroll.policies": ("PayrollPolicy", "policy_id"),
    "payroll.pay_item_definitions": ("PayItem", "pay_item_id"),
    "payroll.insurance_configs": ("InsuranceConfig", "insurance_config_id"),
    "payroll.tax_brackets": ("TaxBracket", "tax_bracket_id"),
    "payroll.tax_exemptions": ("TaxExemption", "tax_exemption_id"),
    "payroll.overtime_rules": ("OvertimeRule", "overtime_rule_id"),
    "payroll.minimum_wage_rates": ("MinimumWageRate", "minimum_wage_rate_id"),
    "payroll.employee_pay_components": ("EmployeePayComponent", "component_id"),
    "payroll.description_templates": ("PayrollDescriptionTemplate", "company_id"),
}
# شمارنده‌ها و زمان‌های فنی با هر سند یا ورود عوض می‌شوند و ردپا نمی‌خواهند
_SKIP = {"next_number", "created_at", "valid_from", "failed_login_count", "locked_until", "password_changed_at"}
_SECRET = {"password_hash", "password_salt"}
_PENDING = "_audit_trail_pending"


def _spec(obj) -> tuple[str, str] | None:
    table = getattr(obj, "__table__", None)
    return _TRACKED.get(table.fullname) if table is not None else None


def _plain(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def _snapshot(obj) -> dict:
    out = {}
    for column in obj.__table__.columns:
        if column.name in _SKIP or column.name in _SECRET:
            continue
        value = getattr(obj, column.key, None)
        if not isinstance(value, (bytes, bytearray, memoryview)):
            out[column.name] = _plain(value)
    return out


def _diff(obj) -> dict:
    state, out = inspect(obj), {}
    for column in obj.__table__.columns:
        if column.name in _SKIP:
            continue
        history = state.attrs[column.key].history
        if not history.added:
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0]
        if column.name in _SECRET:
            out["password"] = "تغییر کرد"
        elif old != new and not isinstance(new, (bytes, bytearray, memoryview)):
            out[column.name] = [_plain(old), _plain(new)]
    return out


def actor_id() -> int | None:
    from peecha import session as app_session

    return getattr(app_session.current_user, "user_id", None)


def _company_id(session: Session, obj) -> int | None:
    company_id = getattr(obj, "company_id", None)
    if company_id is None and getattr(obj, "role_id", None) is not None:
        from peecha.db.models.security import Role

        with session.no_autoflush:
            role = session.get(Role, obj.role_id)
        company_id = role.company_id if role is not None else None
    if company_id is None:
        from peecha import session as app_session

        company_id = getattr(app_session.current_company, "company_id", None)
    return company_id


@event.listens_for(Session, "before_flush")
def _collect(session: Session, _flush_context, _instances) -> None:
    pending = session.info.setdefault(_PENDING, [])
    for obj in session.new:
        if _spec(obj):
            pending.append((obj, "CREATE", None))
    for obj in session.dirty:
        if _spec(obj) and session.is_modified(obj, include_collections=False):
            changes = _diff(obj)
            if changes:
                pending.append((obj, "UPDATE", changes))
    for obj in session.deleted:
        spec = _spec(obj)
        if spec:
            pending.append((obj, "DELETE", _snapshot(obj) | {"_id": getattr(obj, spec[1], None),
                                                            "_company": _company_id(session, obj)}))


@event.listens_for(Session, "after_flush")
def _write(session: Session, _flush_context) -> None:
    pending = session.info.pop(_PENDING, None)
    if not pending:
        return
    from peecha.db.models.audit import ActivityLog

    user_id = session.info.get("actor_user_id") or actor_id()
    for obj, action, changes in pending:
        entity_type, id_attr = _spec(obj)
        if action == "DELETE":
            entity_id, company_id = changes.pop("_id"), changes.pop("_company")
        else:
            entity_id, company_id = getattr(obj, id_attr, None), _company_id(session, obj)
            if action == "CREATE":
                changes = _snapshot(obj)
        if entity_id is None:
            continue
        session.add(ActivityLog(company_id=company_id, user_id=user_id, entity_type=entity_type, entity_id=int(entity_id),
                                action=action, changes=changes or {}))


@event.listens_for(Session, "after_soft_rollback")
def _discard(session: Session, _previous_transaction) -> None:
    session.info.pop(_PENDING, None)
