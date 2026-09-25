"""ورود/تمدید/خروجِ اپِ موبایل -- طبقِ تصمیمِ تاییدشده: همان حسابِ
کاربریِ ERP، فقط با یک توکنِ مخصوصِ همین دستگاه که تا وقتِ ابطال معتبر
است (بازکردنِ روزانهٔ اپ نیازی به لاگینِ دوباره ندارد)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.core import Company
from peecha.db.models.security import UserCompany
from peecha.services import auth as auth_service
from peecha.services import roles as roles_service
from peecha.services import users as users_service
from peecha.services import vehicle_settlement as vehicle_settlement_service
from peecha.services import vehicle_team as vehicle_team_service
from peecha_api import security
from peecha_api.deps import AuthContext, get_current_context
from peecha_api.rate_limit import enforce_login_rate_limit
from peecha_api.schemas import (
    AccessTokenResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _resolve_company_for_user(user_id: int) -> tuple[int, str]:
    with new_session() as session:
        rows = session.execute(
            select(UserCompany, Company)
            .join(Company, Company.company_id == UserCompany.company_id)
            .where(UserCompany.user_id == user_id)
            .order_by(UserCompany.is_default.desc())
        ).all()
        if not rows:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="این کاربر به هیچ شرکتی دسترسی ندارد.")
        _user_company, company = rows[0]
        return company.company_id, company.display_name


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request) -> TokenResponse:
    enforce_login_rate_limit(request, payload.username)
    user = auth_service.authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="نامِ‌کاربری یا رمزِ عبور نادرست است.")
    company_id, company_name = _resolve_company_for_user(user.user_id)
    _device_token_id, refresh_token = security.create_device_token(user.user_id, company_id, payload.device_name)
    access_token = security.create_access_token(user.user_id, company_id)
    return TokenResponse(
        access_token=access_token, refresh_token=refresh_token, user_id=user.user_id, full_name=user.full_name,
        company_id=company_id, company_name=company_name,
    )


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(payload: RefreshRequest) -> AccessTokenResponse:
    resolved = security.resolve_refresh_token(payload.refresh_token)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="توکنِ رفرش نامعتبر، منقضی یا باطل‌شده است.")
    _device_token_id, user_id, company_id = resolved
    return AccessTokenResponse(access_token=security.create_access_token(user_id, company_id))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: LogoutRequest) -> None:
    resolved = security.resolve_refresh_token(payload.refresh_token)
    if resolved is None:
        return
    device_token_id, _user_id, company_id = resolved
    security.revoke_device_token(device_token_id, company_id)


@router.get("/me")
def me(ctx: AuthContext = Depends(get_current_context)) -> dict:
    """طبقِ درخواستِ صریح («تعیینِ کانالِ مجزا برایِ پخشِ سرد و گرم»): چون
    بازکردنِ روزانهٔ اپ لاگینِ دوباره نمی‌زند (توکنِ ذخیره‌شده معتبر
    می‌ماند)، این مقدار نباید فقط در پاسخِ /auth/login باشد -- اپِ موبایل
    آن را هر بار با یک درخواستِ جدا (هم‌الگو با /pricing/channels) پس از
    ورود می‌خواند."""
    channel_type = users_service.get_mobile_channel_type(ctx.user_id, ctx.company_id)
    # طبقِ رفعِ باگِ واقعی («در هر سه نقش خودم را گذاشتم ولی فاکتورِ
    # موبایل می‌گوید خودرویی وصل نیست»): قبلاً این مقدار فقط وقتی برگردانده
    # می‌شد که «نوعِ کانالِ موبایلِ» کاربر در تنظیماتِ کاربرانِ دسکتاپ
    # VAN_SALES بود -- ولی از R205 خودِ ویزیتور حالتِ گرم/سرد را در
    # موبایل انتخاب می‌کند و آن تنظیم فقط پیشنهادِ پیش‌فرض است. پس
    # همیشه برگردانده می‌شود؛ موبایل فقط در حالتِ پخشِ گرم از آن استفاده
    # می‌کند.
    assigned_vehicle_warehouse_id = vehicle_team_service.get_assigned_vehicle_warehouse_id(
        ctx.user_id, ctx.company_id, "VISITOR",
    )
    # طبقِ درخواستِ صریح («تسویه آخر روز باید بصورتِ انتخابی به یک نفر از
    # ۳ نقش واگذار بشه»): نقشِ مسئولِ تسویه لزوماً VISITOR نیست (می‌تواند
    # DRIVER/DISTRIBUTOR هم باشد) -- پس جدا از assigned_vehicle_warehouse_id
    # بالا محاسبه می‌شود.
    settlement_vehicle_warehouse_id = vehicle_settlement_service.get_settlement_vehicle_for_user(ctx.user_id, ctx.company_id)
    return {
        "mobile_channel_type_code": channel_type,
        "assigned_vehicle_warehouse_id": assigned_vehicle_warehouse_id,
        "settlement_vehicle_warehouse_id": settlement_vehicle_warehouse_id,
        # طبقِ درخواستِ صریحِ کاربر («امکاناتِ مدیریتی -- تاییدِ مشتری،
        # داشبوردِ سرپرست»): موبایل بدونِ این، مجبور بود کورکورانه دکمه‌ها
        # را نشان بدهد و فقط رویِ خطایِ ۴۰۳ تشخیص بدهد.
        "is_manager": roles_service.is_manager(ctx.user_id, ctx.company_id),
    }
