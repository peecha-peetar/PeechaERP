"""فعال‌سازیِ RBACِ موجود (sec.role_form_permissions) رویِ APIِ موبایل --
طبقِ کشفِ حسابرسی: این جدول‌ها از اول بودند ولی هیچ‌جایِ برنامه enforce
نمی‌شدند (roles_service.user_has_permission تازه برایِ همین اضافه شد).
هیچ سیستمِ دسترسیِ جداگانه‌ای برایِ موبایل ساخته نمی‌شود -- همان کدهایِ
فرمِ دسکتاپ (nav_catalog.py) این‌جا هم استفاده می‌شوند."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from peecha.services import roles as roles_service
from peecha_api.deps import AuthContext, get_current_context

# طبقِ roles.py::build_form_catalog: کدِ فرمِ ذخیره‌شده در sec.forms
# همان "screen" هرِ آیتمِ nav_catalog.py است، نه "code"ِ کوتاهِ آن --
# این‌جا یک‌بار درست map می‌شود تا در همه‌یِ روترها استفاده شود.
FORM_CUSTOMER_MANAGEMENT = "detail_dimensions"  # nav code: GL_DIM
FORM_TREASURY_RECEIPT = "treasury_voucher_receipt"  # nav code: TREASURY_RECEIPT
FORM_COLD_DISTRIBUTION = "cold_distribution"  # nav code: SALES_COLD_DISTRIBUTION
FORM_HOT_DISTRIBUTION = "commercial_distribution_hub"  # nav code: SALES_DISTRIBUTION


def require_permission(form_code: str, action_code: str):
    def _check(ctx: AuthContext = Depends(get_current_context)) -> AuthContext:
        if not roles_service.user_has_permission(ctx.user_id, ctx.company_id, form_code, action_code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"دسترسیِ لازم ({form_code}/{action_code}) برایِ این عملیات وجود ندارد.",
            )
        return ctx

    return _check
