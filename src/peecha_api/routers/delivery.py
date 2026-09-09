"""تاییدِ تحویل (Proof of Delivery) از موبایل -- امضا/عکس به‌صورتِ
base64 می‌آیند، رویِ دیسک ذخیره می‌شوند (هم‌الگو با ذخیرهٔ ضمائمِ
detail_dimensions.py) و فقط مسیرِ فایل در دیتابیس ذخیره می‌شود؛ خودِ
منطقِ تاییدِ تحویل رویِ services/delivery_confirmation.py (R129) سوار
است."""

from __future__ import annotations

import base64
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from peecha.config import SETTINGS_DIR
from peecha.services import delivery_confirmation as delivery_service
from peecha_api.deps import AuthContext, get_current_context
from peecha_api.schemas import DeliveryConfirmationRequest

router = APIRouter(prefix="/delivery-confirmations", tags=["delivery"])

_MEDIA_DIR = SETTINGS_DIR / "field_sales_media"


def _save_base64(data_base64: str, extension: str) -> str:
    _MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    content = base64.b64decode(data_base64)
    destination = _MEDIA_DIR / f"{uuid.uuid4().hex}.{extension}"
    destination.write_bytes(content)
    return str(destination)


@router.post("")
def create_delivery_confirmation(payload: DeliveryConfirmationRequest, ctx: AuthContext = Depends(get_current_context)) -> dict:
    signature_storage_key = _save_base64(payload.signature_base64, "png") if payload.signature_base64 else None
    photo_storage_key = _save_base64(payload.photo_base64, "jpg") if payload.photo_base64 else None

    try:
        delivery_confirmation_id = delivery_service.create_delivery_confirmation(
            ctx.company_id, payload.document_id, ctx.user_id,
            [
                delivery_service.DeliveryLineFields(line.document_line_id, line.delivered_quantity, line.shortage_reason)
                for line in payload.lines
            ],
            customer_visit_id=payload.customer_visit_id, received_by_name=payload.received_by_name,
            signature_storage_key=signature_storage_key, photo_storage_key=photo_storage_key,
            gps_latitude=payload.gps_latitude, gps_longitude=payload.gps_longitude, notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {"delivery_confirmation_id": delivery_confirmation_id}
