"""حل «چه کسی؟» برای تایید، کار و اعلان -- بر اساس همان کاربران/نقش‌ها/دسترسی‌های موجود پیچا.

مشخصهٔ هر گیرنده: {"kind": ...}
    USER {user_id} · ROLE {role_id} · STARTER (شروع‌کننده) · OWNER (مسئول سند) · FIELD {field} (کاربر داخل سند)
    PERMISSION {form_code, action} · MANAGERS (مدیران شرکت) · RESOLVER {code} (مسیریاب سفارشی)
    ORG_MANAGER {org_unit_id} · REPORTING_MANAGER (مدیر مستقیم شروع‌کننده) · WAREHOUSE {field|warehouse_id}
    AMOUNT_TABLE {field, bands: [{"max": n|None, "approvers": [...]}]}
"""

from __future__ import annotations

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.security import Role, User, UserCompany, UserRole
from peecha.services import roles as roles_service
from peecha.services.workflow import conditions, registry
from peecha.services.workflow.common import WorkflowError

KINDS = {
    "USER": "کاربر مشخص", "ROLE": "همهٔ دارندگان یک نقش", "STARTER": "شروع‌کنندهٔ فرایند", "OWNER": "مسئول سند",
    "FIELD": "کاربر ثبت‌شده در سند", "PERMISSION": "دارندگان مجوز تایید فرم", "MANAGERS": "مدیران شرکت",
    "ORG_MANAGER": "مدیر واحد سازمانی", "REPORTING_MANAGER": "مدیر مستقیم درخواست‌کننده",
    "WAREHOUSE": "کاربران انبار سند", "AMOUNT_TABLE": "بر اساس سقف مبلغ", "RESOLVER": "مسیریاب سفارشی",
}


def company_users(session, company_id: int) -> list[int]:
    return list(session.scalars(select(User.user_id).join(UserCompany, UserCompany.user_id == User.user_id).where(
        UserCompany.company_id == company_id, User.is_active.is_(True))))


def role_users(session, company_id: int, role_id: int) -> list[int]:
    return list(session.scalars(select(UserRole.user_id).join(User, User.user_id == UserRole.user_id).where(
        UserRole.role_id == role_id, UserRole.company_id == company_id, User.is_active.is_(True))))


def role_names(session, role_ids) -> dict[int, str]:
    ids = {r for r in role_ids if r}
    return dict(session.execute(select(Role.role_id, Role.code).where(Role.role_id.in_(ids)))) if ids else {}


def describe_spec(spec: dict, role_label: dict[int, str] | None = None, user_label: dict[int, str] | None = None) -> str:
    kind = spec.get("kind")
    if kind == "USER":
        return (user_label or {}).get(spec.get("user_id"), f"کاربر {spec.get('user_id')}")
    if kind == "ROLE":
        return f"نقش «{(role_label or {}).get(spec.get('role_id'), spec.get('role_id'))}»"
    if kind == "PERMISSION":
        return "دارندگان مجوز تایید فرم"
    if kind == "FIELD":
        return f"کاربر ثبت‌شده در «{spec.get('field')}»"
    if kind == "RESOLVER":
        r = registry.resolvers().get(spec.get("code") or "")
        return r.label if r else str(spec.get("code"))
    return KINDS.get(kind, str(kind))


def resolve(company_id: int, specs: list[dict], *, context: dict | None = None, starter: int | None = None,
            entity_type: str | None = None, entity_id: int | None = None) -> list[int]:
    """کاربران فعال شرکت که با مشخصه‌ها منطبق‌اند (یکتا، به ترتیب ثابت)."""
    context = context or {}
    out: list[int] = []
    with new_session() as session:
        members = set(company_users(session, company_id))
        for spec in specs or []:
            kind = spec.get("kind")
            ids: list[int] = []
            if kind == "USER":
                ids = [spec.get("user_id")]
            elif kind == "ROLE":
                ids = role_users(session, company_id, spec.get("role_id"))
            elif kind == "STARTER":
                ids = [starter]
            elif kind == "OWNER":
                adapter = registry.get_adapter(entity_type)
                owner = adapter.owner(company_id, entity_id) if adapter and adapter.owner and entity_id else None
                ids = [owner or context.get("owner_user_id")]
            elif kind == "FIELD":
                value = conditions.get_path(context, spec.get("field") or "")
                ids = list(value) if isinstance(value, (list, tuple)) else [value]
            elif kind == "PERMISSION":
                form, action = spec.get("form_code"), spec.get("action") or "APPROVE"
                if not form:
                    adapter = registry.get_adapter(entity_type)
                    form = adapter.form_code if adapter else None
                ids = [u for u in sorted(members) if form and roles_service.user_has_permission(u, company_id, form, action)]
            elif kind == "MANAGERS":
                ids = [u for u in sorted(members) if roles_service.is_manager(u, company_id)]
            elif kind == "AMOUNT_TABLE":
                amount = conditions._number(conditions.get_path(context, spec.get("field") or "amount")) or 0
                for band in spec.get("bands") or []:
                    top = conditions._number(band.get("max"))
                    if top is None or amount <= top:
                        ids = resolve(company_id, band.get("approvers") or [], context=context, starter=starter,
                                      entity_type=entity_type, entity_id=entity_id)
                        break
            elif kind in _EXTRA_KINDS:
                ids = _EXTRA_KINDS[kind](session, company_id, spec, context, starter, entity_type, entity_id)
            elif kind == "RESOLVER":
                r = registry.resolvers().get(spec.get("code") or "")
                if r is None:
                    raise WorkflowError(f"مسیریاب «{spec.get('code')}» شناخته نشده است.")
                ids = r.func(company_id=company_id, context=context, starter=starter, entity_type=entity_type,
                             entity_id=entity_id, params=spec.get("params") or {})
            for uid in ids:
                try:
                    uid = int(uid) if uid not in (None, "") else None
                except (TypeError, ValueError):
                    uid = None
                if uid and uid in members and uid not in out:
                    out.append(uid)
    return out


# R292: مسیریاب‌های سازمانی (مدیر واحد، مدیر مستقیم، انبار) اینجا ثبت می‌شوند
_EXTRA_KINDS: dict = {}


def register_kind(kind: str, func) -> None:
    _EXTRA_KINDS[kind] = func
