"""سرویس نقش‌ها و دسترسی‌ها (sec.roles + sec.role_form_permissions +
sec.user_roles). کاتالوگِ ماژول/فرم (sec.modules/sec.forms) چون داده‌ی
ثابتِ خودِ برنامه است (نه چیزی که کاربر تعریف کند)، با ensure_catalog()
به‌صورت خودکار/idempotent در دیتابیس ساخته می‌شود — دقیقاً همان الگوی
get-or-create که برای سال مالی در journal_entries.py استفاده شده.

فقط ۴ اکشنِ VIEW/CREATE/EDIT/DELETE در این نسخه قابل‌تنظیم‌اند (نه همه‌ی
۷ اکشنِ جدولِ permission_actions) — چون فقط همین‌ها در فرم‌های فعلی برنامه
واقعاً معنا دارند (چاپ/خروجی/تایید هنوز به هیچ صفحه‌ای وصل نشده)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.security import (
    Form,
    Module,
    PermissionAction,
    Role,
    RoleFormPermission,
    User,
    UserRole,
)

# (کدِ ماژول، برچسبِ فارسی، آیکون، ترتیب) — همان ماژول‌های شِل (shell.py NAV_ITEMS)
_MODULES = [
    ("DASH", "داشبورد", "view-dashboard-outline", 0),
    ("GL", "مالی و حسابداری", "cash-multiple", 1),
    ("INV", "انبار و موجودی", "package-variant-closed", 2),
    ("SALES", "فروش و بازاریابی", "cart-outline", 3),
    ("PURCH", "خرید و تدارکات", "truck-outline", 4),
    ("HR", "منابع انسانی", "account-group-outline", 5),
    ("INVOICES", "فاکتورها", "receipt-text-outline", 6),
    ("REPORTS", "گزارش‌ها", "chart-bar", 7),
    ("SETTINGS", "مدیریت سیستم", "cog-outline", 8),
]

# (کدِ فرم = همان name صفحه‌ی Kivy، کدِ ماژول، برچسبِ فارسی)
_FORMS = [
    ("dashboard", "DASH", "داشبورد"),
    ("chart_of_accounts", "GL", "کدینگ حسابداری"),
    ("journal_entry", "GL", "صدور سند"),
    ("languages", "SETTINGS", "زبان‌ها"),
    ("companies", "SETTINGS", "شرکت‌ها"),
    ("fiscal_years", "SETTINGS", "سال‌های مالی"),
    ("users", "SETTINGS", "کاربران"),
    ("roles", "SETTINGS", "نقش‌ها و دسترسی‌ها"),
]

FORM_LABELS: dict[str, str] = {code: label for code, _module, label in _FORMS}
MODULE_LABELS: dict[str, str] = {code: label for code, label, _icon, _sort in _MODULES}


def ensure_catalog() -> None:
    with new_session() as session:
        existing_modules = {m.code for m in session.scalars(select(Module))}
        for code, _label, icon, sort_order in _MODULES:
            if code not in existing_modules:
                session.add(Module(code=code, icon_name=icon, sort_order=sort_order, is_active=True))
        session.flush()

        modules_by_code = {m.code: m.module_id for m in session.scalars(select(Module))}
        existing_forms = {f.code for f in session.scalars(select(Form))}
        for code, module_code, _label in _FORMS:
            if code not in existing_forms:
                session.add(Form(module_id=modules_by_code[module_code], code=code, is_active=True))
        session.commit()


@dataclass
class FormOption:
    form_id: int
    code: str
    module_code: str
    label: str


def list_forms() -> list[FormOption]:
    ensure_catalog()
    with new_session() as session:
        modules_by_id = {m.module_id: m.code for m in session.scalars(select(Module))}
        forms = session.scalars(select(Form).order_by(Form.module_id, Form.form_id)).all()
        return [
            FormOption(
                form_id=f.form_id,
                code=f.code,
                module_code=modules_by_id[f.module_id],
                label=FORM_LABELS.get(f.code, f.code),
            )
            for f in forms
        ]


@dataclass
class RoleRow:
    role_id: int
    code: str
    parent_role_id: int | None
    parent_code: str | None
    is_active: bool


def list_roles(company_id: int) -> list[RoleRow]:
    with new_session() as session:
        roles = session.scalars(
            select(Role).where(Role.company_id == company_id).order_by(Role.code)
        ).all()
        codes_by_id = {r.role_id: r.code for r in roles}
        return [
            RoleRow(
                role_id=r.role_id,
                code=r.code,
                parent_role_id=r.parent_role_id,
                parent_code=codes_by_id.get(r.parent_role_id) if r.parent_role_id else None,
                is_active=r.is_active,
            )
            for r in roles
        ]


def create_role(company_id: int, code: str, parent_role_id: int | None) -> Role:
    with new_session() as session:
        if session.scalar(select(Role).where(Role.company_id == company_id, Role.code == code)):
            raise ValueError("این کدِ نقش قبلاً در این شرکت تعریف شده است.")
        role = Role(company_id=company_id, parent_role_id=parent_role_id, code=code, is_active=True)
        session.add(role)
        session.commit()
        session.refresh(role)
        session.expunge(role)
        return role


def update_role(role_id: int, company_id: int, parent_role_id: int | None, is_active: bool) -> Role:
    with new_session() as session:
        role = session.get(Role, role_id)
        if role is None or role.company_id != company_id:
            raise ValueError("نقش نامعتبر است.")
        if parent_role_id == role_id:
            raise ValueError("یک نقش نمی‌تواند والدِ خودش باشد.")
        if role.is_system_role and not is_active:
            raise ValueError("نقش‌های سیستمی غیرقابل‌غیرفعال‌سازی‌اند.")
        role.parent_role_id = parent_role_id
        role.is_active = is_active
        session.commit()
        session.refresh(role)
        session.expunge(role)
        return role


def get_role_permissions(role_id: int) -> set[tuple[int, str]]:
    """مجموعه‌ی (form_id, action_code) هایی که برای این نقش صریحاً مجازند."""
    with new_session() as session:
        action_codes = {a.action_id: a.code for a in session.scalars(select(PermissionAction))}
        rows = session.scalars(
            select(RoleFormPermission).where(
                RoleFormPermission.role_id == role_id, RoleFormPermission.is_allowed.is_(True)
            )
        ).all()
        return {(r.form_id, action_codes[r.action_id]) for r in rows}


def set_role_permission(role_id: int, form_id: int, action_code: str, is_allowed: bool) -> None:
    with new_session() as session:
        action = session.scalar(select(PermissionAction).where(PermissionAction.code == action_code))
        if action is None:
            raise ValueError("اکشنِ دسترسیِ نامعتبر است.")
        existing = session.get(RoleFormPermission, {"role_id": role_id, "form_id": form_id, "action_id": action.action_id})
        if existing is None:
            if is_allowed:
                # مدلِ ORM (برخلافِ مثلاً Company.created_at) هیچ default یی برای
                # valid_from ندارد، فقط خودِ ستونِ دیتابیس DEFAULT now() دارد؛ چون
                # SQLAlchemy مقدارِ Python-side ست‌نشده را همچنان NULL می‌فرستد
                # (نه این‌که حذفش کند)، باید اینجا صریح مقداردهی شود — با تست
                # مستقیم پیدا شد (NotNullViolation).
                session.add(
                    RoleFormPermission(
                        role_id=role_id,
                        form_id=form_id,
                        action_id=action.action_id,
                        is_allowed=True,
                        valid_from=datetime.datetime.now(datetime.timezone.utc),
                    )
                )
        elif not is_allowed:
            session.delete(existing)
        session.commit()


@dataclass
class RoleUserRow:
    user_id: int
    full_name: str
    assigned: bool


def list_role_users(role_id: int, company_id: int) -> list[RoleUserRow]:
    with new_session() as session:
        users = session.scalars(select(User).order_by(User.username)).all()
        assigned_ids = {
            ur.user_id
            for ur in session.scalars(
                select(UserRole).where(UserRole.role_id == role_id, UserRole.company_id == company_id)
            )
        }
        return [
            RoleUserRow(user_id=u.user_id, full_name=u.full_name, assigned=u.user_id in assigned_ids)
            for u in users
        ]


def set_user_role(user_id: int, role_id: int, company_id: int, assigned: bool) -> None:
    with new_session() as session:
        existing = session.get(UserRole, {"user_id": user_id, "role_id": role_id, "company_id": company_id})
        if assigned and existing is None:
            # همان دلیلِ valid_from صریح در set_role_permission بالا.
            session.add(
                UserRole(
                    user_id=user_id,
                    role_id=role_id,
                    company_id=company_id,
                    valid_from=datetime.datetime.now(datetime.timezone.utc),
                )
            )
        elif not assigned and existing is not None:
            session.delete(existing)
        session.commit()
