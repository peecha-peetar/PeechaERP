"""حذف یک حساب تفصیلی از هر گروه (R301) — همان مسیر فرم «تعریف تفصیلی»، قابل استفاده از هر فهرست.

مشتری/تامین‌کننده/پرسنل با سرویس اختصاصی خودشان، کالا با حذف کالا (همراه متغیرها و تعریف‌های خودش، با پیام دقیق
«کجا استفاده شده») و بقیهٔ گروه‌ها با حذف عمومی حساب تفصیلی.
"""

from __future__ import annotations

from dataclasses import dataclass

from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service


def _person_delete_fns() -> dict:
    from peecha.services import commercial_partners as partners_service, hr as hr_service

    return {
        dimensions_service.CUSTOMER_GROUP_CODE: partners_service.delete_customer_detail_account,
        dimensions_service.SUPPLIER_GROUP_CODE: partners_service.delete_supplier_detail_account,
        dimensions_service.PERSONNEL_GROUP_CODE: hr_service.delete_personnel_detail_account,
    }


@dataclass
class DeletePlan:
    item_id: int | None
    parent_item_id: int | None  # اگر خودش متغیر یک کالای اصلی است
    variant_count: int  # تعداد متغیرهایی که همراهش حذف می‌شوند
    confirm_text: str


def plan(company_id: int, detail_account_id: int, name: str = "") -> DeletePlan:
    """پیش از حذف: متن تاییدی که دقیقاً می‌گوید چه چیزی پاک می‌شود."""
    label = f"«{name}»" if name else "این حساب"
    item = catalog_service.get_item_row_by_detail_account_id(company_id, detail_account_id)
    if item is None:
        return DeletePlan(None, None, 0, f"{label} حذف شود؟ این کار قابل بازگشت نیست.")
    variants = catalog_service.variant_ids(company_id, item.item_id)
    if variants:
        text = (f"{label} {len(variants)} متغیر دارد. با حذف آن، همهٔ متغیرهایش هم حذف می‌شوند "
                "(اگر هیچ‌کدام در سند یا گردشی استفاده نشده باشد). ادامه می‌دهید؟")
    else:
        text = f"{label} حذف شود؟ این کار قابل بازگشت نیست."
    return DeletePlan(item.item_id, item.variant_parent_item_id, len(variants), text)


def delete(company_id: int, detail_account_id: int, *, person_group_code: str | None = None) -> None:
    """ValueError با پیام فارسی دقیق اگر حذف ممکن نباشد (مثلاً «در این بخش‌ها استفاده شده: ...»)."""
    if person_group_code:
        fn = _person_delete_fns().get(person_group_code)
        if fn is None:
            raise ValueError("گروه تفصیلی نامعتبر است.")
        fn(detail_account_id, company_id)
        return
    item = catalog_service.get_item_row_by_detail_account_id(company_id, detail_account_id)
    if item is None:
        dimensions_service.delete_detail_account(detail_account_id, company_id)
        return
    if item.variant_parent_item_id is not None:
        from peecha.services import item_variants

        item_variants.delete_item_variant(company_id, item.variant_parent_item_id, item.item_id)
        return
    catalog_service.delete_item(item.item_id, company_id, with_variants=True)
