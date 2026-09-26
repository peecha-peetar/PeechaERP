"""درختِ مسیر/منطقه‌یِ توزیع -- رویِ همان نوع‌بُعدِ تخصصیِ از قبل موجودِ
DISTRIBUTION_ROUTE (detail_dimensions.py، استفاده‌شده در فیلترهایِ
distribution_team.py از R177). هیچ مدل/جدولِ تازه‌ای برایِ «Route»
ساخته نمی‌شود."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from peecha.services import detail_dimensions as dimensions_service
from peecha_api.deps import AuthContext, get_current_context

router = APIRouter(prefix="/routes", tags=["routes"])


@router.get("")
def list_routes(ctx: AuthContext = Depends(get_current_context)) -> list[dict]:
    dimension_type_id = dimensions_service.get_specialized_dimension_type_id(
        ctx.company_id, dimensions_service.DISTRIBUTION_ROUTE_CODE
    )
    rows = dimensions_service.list_detail_accounts(ctx.company_id, dimension_type_id)
    return [
        {
            "detail_account_id": r.detail_account_id,
            "code": r.code,
            "name": r.name,
            "parent_detail_account_id": r.parent_detail_account_id,
            "level_no": r.level_no,
            "full_code": r.full_code,
            "is_active": r.is_active,
        }
        for r in rows
    ]
