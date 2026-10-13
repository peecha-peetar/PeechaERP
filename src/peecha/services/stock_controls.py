"""R303 — کنترل‌های قابل روشن/خاموش انبار (تنظیمات › انبار › قابلیت‌های فعال).

هر کنترل پیش‌فرض خاموش است؛ با کلید خاموش رفتار دقیقاً همان قبلی است.
soft یعنی سند (فروش موبایل که کالایش تحویل شده) رد نمی‌شود و تخلف فقط به‌صورت هشدار ثبت می‌شود.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.inventory import CompanyFeature, Warehouse, WarehouseUserAccess

RESERVATION = "WMS_ENFORCE_RESERVATION"
SALES_ORDER_RESERVATION = "WMS_SALES_ORDER_RESERVATION"
LOCATION_STATUS = "WMS_LOCATION_STATUS_CONTROL"
EXPIRED = "WMS_BLOCK_EXPIRED_ISSUE"
WAREHOUSE_ACCESS = "WMS_ENFORCE_WAREHOUSE_ACCESS"
MOBILE_PERMISSIONS = "WMS_DETAILED_MOBILE_PERMISSIONS"
SCAN_CONFIRMATION = "WMS_SCAN_CONFIRMATION"  # R304
PUTAWAY_IN_CARTABLE = "WMS_PUTAWAY_IN_CARTABLE"  # R304
PICK_CONTROL = "WMS_PICK_CONTROL"  # R305
COUNT_RECONCILE = "WMS_COUNT_RECONCILE"  # R306
QC_HOLD = "WMS_QC_HOLD"  # R306
ALL = (RESERVATION, SALES_ORDER_RESERVATION, LOCATION_STATUS, EXPIRED, WAREHOUSE_ACCESS, MOBILE_PERMISSIONS,
       SCAN_CONFIRMATION, PUTAWAY_IN_CARTABLE, PICK_CONTROL, COUNT_RECONCILE, QC_HOLD)

# انواع سندی که رزرو دیگران را نباید مصرف کنند (اصلاح موجودی = واقعیت شمارش، مستثنا)
RESERVATION_TYPES = ("ISSUE", "TRANSFER", "RETURN_OUT")
# مقصدهایی که خروج کالای منقضی/قرنطینه به آن‌ها مجاز است
DISPOSAL_WAREHOUSE_TYPES = ("SCRAP", "QUARANTINE")


@dataclass
class Controls:
    company_id: int
    soft: bool = False
    reservation: bool = False
    location_status: bool = False
    expired: bool = False
    warehouse_access: bool = False
    warnings: list[str] = field(default_factory=list)

    def violate(self, message: str) -> None:
        if self.soft:
            if message not in self.warnings:
                self.warnings.append(message)
            return
        raise ValueError(message)


def enabled_codes(company_id: int, session=None) -> set[str]:
    q = select(CompanyFeature.feature_code).where(
        CompanyFeature.company_id == company_id, CompanyFeature.is_enabled.is_(True), CompanyFeature.feature_code.in_(ALL))
    if session is not None:
        return set(session.scalars(q))
    with new_session() as s:
        return set(s.scalars(q))


def is_on(company_id: int, code: str, session=None) -> bool:
    return code in enabled_codes(company_id, session)


def load(company_id: int, soft: bool = False, session=None) -> Controls:
    on = enabled_codes(company_id, session)
    return Controls(company_id, soft=soft, reservation=RESERVATION in on, location_status=LOCATION_STATUS in on,
                    expired=EXPIRED in on, warehouse_access=WAREHOUSE_ACCESS in on)


# ---------------------------------------------------------------------
# دسترسی کاربر به انبار (inv.warehouse_user_access)
# ---------------------------------------------------------------------
_FLAG_BY_ACTION = {"VIEW": "can_view_balance", "RECEIPT": "can_post_receipt", "ISSUE": "can_post_issue",
                   "ADJUST": "can_adjust"}
_ACTION_LABEL = {"VIEW": "دیدن موجودی", "RECEIPT": "ثبت رسید", "ISSUE": "ثبت حواله", "ADJUST": "اصلاح موجودی"}


def _is_super_admin(session, user_id: int | None) -> bool:
    from peecha.db.models.security import User

    user = session.get(User, user_id) if user_id is not None else None
    return bool(user is not None and user.is_super_admin)


def warehouse_allows(session, warehouse_id: int, user_id: int | None, action: str) -> bool:
    """انبار بدون فهرست کاربر = آزاد برای همه؛ مدیر کل همیشه مجاز."""
    rows = list(session.scalars(select(WarehouseUserAccess).where(WarehouseUserAccess.warehouse_id == warehouse_id)))
    if not rows or _is_super_admin(session, user_id):
        return True
    row = next((r for r in rows if r.user_id == user_id), None)
    return row is not None and bool(getattr(row, _FLAG_BY_ACTION[action]))


def check_warehouse_access(session, controls: Controls, user_id: int | None, moves: list[tuple[int, str]]) -> None:
    """moves: [(انبار، RECEIPT|ISSUE|ADJUST)]."""
    if not controls.warehouse_access:
        return
    for warehouse_id, action in dict.fromkeys(moves):
        if warehouse_id is None or warehouse_allows(session, warehouse_id, user_id, action):
            continue
        name = session.scalar(select(Warehouse.name).where(Warehouse.warehouse_id == warehouse_id))
        controls.violate(f"شما اجازهٔ {_ACTION_LABEL[action]} در انبار «{name}» را ندارید.")


def visible_warehouse_ids(company_id: int, user_id: int, warehouse_ids: list[int]) -> set[int]:
    """برای نمایش موجودی (موبایل): با کلید خاموش همه."""
    if not is_on(company_id, WAREHOUSE_ACCESS):
        return set(warehouse_ids)
    with new_session() as session:
        return {w for w in warehouse_ids if warehouse_allows(session, w, user_id, "VIEW")}


def is_expired(expiry_date: datetime.date | None, on_date: datetime.date) -> bool:
    return expiry_date is not None and expiry_date < on_date
