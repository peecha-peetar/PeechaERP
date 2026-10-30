"""R350: محدودیت دسترسی کاربر به شعبه‌ها.

کاربری که در یک شرکت شعبه‌ای برایش تعیین نشده (و مدیر کل) به همه دسترسی دارد. کاربر محدود فقط اسناد بازرگانی و
گزارش‌های خرید و فروش شعبه‌های خودش را می‌بیند، فقط انبارها و شعبه‌های خودش را انتخاب می‌کند و سند شعبهٔ دیگر را
باز، ذخیره یا ثبت نمی‌کند. سند و انبار بدون شعبه برای همه است. کاربر از session دسکتاپ خوانده می‌شود؛ جایی که کاربری
تعیین نشده (سرور موبایل، کارهای پس‌زمینه) محدودیتی اعمال نمی‌شود."""

from __future__ import annotations

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.commercial import Branch
from peecha.db.models.inventory import Warehouse
from peecha.db.models.security import User, UserBranch


def _current_user_id() -> int | None:
    from peecha import session as app_session

    user = app_session.current_user
    return user.user_id if user is not None else None


def allowed_branch_ids(company_id: int, user_id: int | None = None) -> frozenset[int] | None:
    """شعبه‌های مجاز؛ None یعنی بدون محدودیت."""
    user_id = user_id or _current_user_id()
    if user_id is None:
        return None
    with new_session() as session:
        user = session.get(User, user_id)
        if user is None or user.is_super_admin:
            return None
        ids = frozenset(session.scalars(select(UserBranch.branch_id).where(
            UserBranch.user_id == user_id, UserBranch.company_id == company_id)))
    return ids or None


def scope(stmt, branch_column, company_id: int):
    """فیلتر کوئری به شعبه‌های مجاز کاربر جاری (و ردیف‌های بدون شعبه)."""
    allowed = allowed_branch_ids(company_id)
    if allowed is None:
        return stmt
    return stmt.where(branch_column.in_(allowed) | branch_column.is_(None))


def ensure_allowed(company_id: int, branch_id: int | None) -> None:
    allowed = allowed_branch_ids(company_id)
    if allowed is not None and branch_id is not None and branch_id not in allowed:
        raise ValueError("این سند یا انبار متعلق به شعبه‌ای است که به آن دسترسی ندارید.")


def is_visible(company_id: int, branch_id: int | None) -> bool:
    allowed = allowed_branch_ids(company_id)
    return allowed is None or branch_id is None or branch_id in allowed


def filter_warehouses(company_id: int, warehouses: list) -> list:
    """WarehouseRowها (inventory_locations) که کاربر جاری مجاز به انتخابشان است."""
    allowed = allowed_branch_ids(company_id)
    if allowed is None:
        return list(warehouses)
    with new_session() as session:
        branch_of = dict(session.execute(select(Warehouse.warehouse_id, Warehouse.branch_id).where(
            Warehouse.company_id == company_id)).all())
    return [w for w in warehouses if branch_of.get(w.warehouse_id) is None or branch_of[w.warehouse_id] in allowed]


def filter_branches(company_id: int, branches: list) -> list:
    allowed = allowed_branch_ids(company_id)
    return list(branches) if allowed is None else [b for b in branches if b.branch_id in allowed]


def get_user_branches(user_id: int, company_id: int) -> list[int]:
    with new_session() as session:
        return sorted(session.scalars(select(UserBranch.branch_id).where(
            UserBranch.user_id == user_id, UserBranch.company_id == company_id)))


def set_user_branches(user_id: int, company_id: int, branch_ids: list[int]) -> None:
    """شعبه‌های مجاز کاربر در این شرکت؛ فهرست خالی یعنی همهٔ شعبه‌ها."""
    wanted = set(branch_ids)
    with new_session() as session:
        valid = set(session.scalars(select(Branch.branch_id).where(Branch.company_id == company_id)))
        if wanted - valid:
            raise ValueError("شعبهٔ انتخاب‌شده متعلق به این شرکت نیست.")
        current = {row.branch_id: row for row in session.scalars(select(UserBranch).where(
            UserBranch.user_id == user_id, UserBranch.company_id == company_id))}
        for branch_id, row in current.items():
            if branch_id not in wanted:
                session.delete(row)
        for branch_id in wanted - set(current):
            session.add(UserBranch(user_id=user_id, company_id=company_id, branch_id=branch_id))
        session.commit()
