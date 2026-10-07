"""دارایی‌های ثابت برای موبایل — R265: اسکن QR/بارکد (مشاهدهٔ دارایی) و ثبت یافتن در شمارش فیزیکی.

نازک: همهٔ منطق در services/fixed_assets؛ دسترسی با RBAC موجود (فرم‌های fa_assets و fa_physical_count).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from peecha.services.fixed_assets import assets as fa
from peecha.services.fixed_assets import common as fac
from peecha.services.fixed_assets import physical as fp
from peecha_api.deps import AuthContext, get_idempotency_key
from peecha_api.idempotency import IdempotentReplay, run_idempotent
from peecha_api.permissions import require_permission

router = APIRouter(prefix="/fixed-assets", tags=["fixed-assets"])
_VIEW = Depends(require_permission("fa_assets", "VIEW"))
_COUNT = Depends(require_permission("fa_physical_count", "EDIT"))
_KEY = Depends(get_idempotency_key)


def _asset_dict(a, show_cost: bool) -> dict:
    from peecha.db.base import new_session

    with new_session() as session:
        location = fac.location_path(session, a.location_id)
    return {"asset_id": a.asset_id, "code": a.asset_code, "name": a.name, "status": a.status_code,
            "status_label": fac.STATUS_LABELS[a.status_code], "serial_no": a.serial_no, "location": location,
            "location_id": a.location_id, "custodian_employee_id": a.custodian_employee_id,
            "book_value": str(a.book_value) if show_cost else None, "qr": fa.qr_payload(a)}


@router.get("/lookup")
def lookup(code: str, ctx: AuthContext = _VIEW) -> dict:
    """اسکن QR یا بارکد دارایی → اطلاعات دارایی (ارزش فقط با دسترسی «مشاهدهٔ بها»)."""
    from peecha.services import roles as roles_service

    asset = fa.find_by_code(ctx.company_id, code)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="دارایی یافت نشد.")
    return _asset_dict(asset, roles_service.user_has_permission(ctx.user_id, ctx.company_id, "fa_cost_view", "VIEW"))


@router.get("/counts")
def open_counts(ctx: AuthContext = _VIEW) -> list[dict]:
    return [{"count_id": c.count_id, "code": c.code, "date": c.count_date.isoformat(), "location_id": c.location_id}
            for c in fp.list_counts(ctx.company_id) if c.status_code == "OPEN"]


class ScanIn(BaseModel):
    code: str
    found_location_id: int | None = None
    found_custodian_employee_id: int | None = None
    damaged: bool = False
    note: str | None = None


@router.post("/counts/{count_id}/scan")
def scan(count_id: int, body: ScanIn, ctx: AuthContext = _COUNT, idempotency_key: str | None = _KEY) -> dict:
    """ثبت یافتن دارایی در شمارش از موبایل (روش: MOBILE)؛ تکرار همان کلید پاسخ قبلی را برمی‌گرداند."""
    def compute():
        return fp.scan(ctx.company_id, count_id, body.code, body.found_location_id, body.found_custodian_employee_id,
                       damaged=body.damaged, method="MOBILE", note=body.note)

    try:
        return run_idempotent(idempotency_key, f"fa_scan:{count_id}", ctx.user_id, ctx.company_id, status.HTTP_200_OK, compute,
                              lambda r: {"asset_id": r.asset_id, "code": r.asset_code, "name": r.name, "result": r.result,
                                         "label": r.label})
    except IdempotentReplay as replay:
        return replay.body
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
