"""R318: تعریف دارایی ثابت از فرم «تعریف تفصیلی» (مثل کالا).

حساب تفصیلی و شناسنامهٔ دارایی در یک تراکنش ساخته می‌شوند و تفصیلی در همان سطح/والدی می‌نشیند که کاربر در فرم انتخاب
کرده؛ اعتبارسنجی‌ها همان سرویس‌های دارایی و تفصیلی است. عملیات مالی (تحصیل، سرمایه‌ای‌کردن، انتقال، ...) همان مسیر
«دارایی‌ها» می‌ماند.
"""

from __future__ import annotations

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.accounting import DetailAccount
from peecha.db.models.fixed_assets import Asset
from peecha.services import detail_dimensions as dims
from peecha.services.fixed_assets import assets as fa
from peecha.services.fixed_assets import common as c

FEATURE = "GL_FA_IN_DETAIL_FORM"


def is_on(company_id: int) -> bool:
    from peecha.services import inventory_engine as engine

    return engine.is_feature_enabled(company_id, FEATURE)


def asset_of_detail(company_id: int, detail_account_id: int) -> Asset | None:
    with new_session() as session:
        asset = session.scalar(select(Asset).where(Asset.company_id == company_id, Asset.detail_account_id == detail_account_id))
        if asset is not None:
            session.expunge(asset)
        return asset


def create(company_id: int, user_id: int | None, code: str, name: str, f: fa.AssetFields, *,
           parent_detail_account_id: int | None = None, detail_account_id: int | None = None,
           extra_fields: dict | None = None) -> int:
    """تفصیلی تازه (یا تفصیلی موجود بی‌دارایی) + دارایی پیش‌نویس؛ خروجی asset_id."""
    code = (code or "").strip()
    name = (name or "").strip()
    if not code:
        raise ValueError("کد را وارد کنید.")
    if not name:
        raise ValueError("نام دارایی الزامی است.")
    with new_session() as session:
        dim_type_id = c._asset_dimension_type_id(session, company_id)
        if detail_account_id is None:
            level_no = 1
            if parent_detail_account_id is not None:
                parent = session.get(DetailAccount, parent_detail_account_id)
                if parent is None or parent.company_id != company_id or parent.dimension_type_id != dim_type_id:
                    raise ValueError("حساب تفصیلی والد نامعتبر است.")
                max_level = dims._get_group_max_level_no(session, dim_type_id)
                if parent.level_no >= max_level:
                    raise ValueError(f"این گروه حداکثر {max_level} سطح می‌تواند داشته باشد.")
                level_no = parent.level_no + 1
            dims._validate_code_length(session, company_id, dim_type_id, level_no, code)
            dims._ensure_code_free(session, company_id, dim_type_id, code)
            detail = DetailAccount(company_id=company_id, dimension_type_id=dim_type_id, code=code, name=name,
                                   parent_detail_account_id=parent_detail_account_id, level_no=level_no,
                                   extra_fields=dict(extra_fields or {}))
            session.add(detail)
            session.flush()
        else:
            detail = session.get(DetailAccount, detail_account_id)
            if detail is None or detail.company_id != company_id or detail.dimension_type_id != dim_type_id:
                raise ValueError("حساب تفصیلی نامعتبر است.")
            if session.scalar(select(Asset.asset_id).where(Asset.detail_account_id == detail_account_id)):
                raise ValueError("این تفصیلی از قبل به یک دارایی وصل است.")
        f.asset_code = (f.asset_code or "").strip() or code
        f.name = name
        asset = fa.insert_asset(session, company_id, user_id, f, detail_account_id=detail.detail_account_id)
        session.commit()
        return asset.asset_id


def update(company_id: int, user_id: int | None, detail_account_id: int, code: str, name: str, is_active: bool,
           f: fa.AssetFields, extra_fields: dict | None = None) -> int:
    """شناسنامهٔ دارایی (با همان قواعد update_asset) و سپس کد/نام/فعال‌بودن تفصیلی."""
    asset = asset_of_detail(company_id, detail_account_id)
    if asset is None:
        raise ValueError("دارایی این تفصیلی یافت نشد.")
    f.asset_code = (f.asset_code or "").strip() or (code or "").strip()
    f.name = (name or "").strip()
    fa.update_asset(company_id, user_id, asset.asset_id, f, reason="ویرایش از فرم تعریف تفصیلی")
    dims.update_detail_account(detail_account_id, company_id, code, is_active, name=f.name, extra_fields=extra_fields)
    return asset.asset_id
