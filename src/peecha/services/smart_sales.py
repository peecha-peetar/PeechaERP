"""زیرساختِ آماده‌یِ Smart Sales/AI (Phase 9) -- طبقِ درخواستِ صریحِ
کاربر: «الزاماً AI واقعی را پیاده‌سازی نکن؛ Architecture را آماده کن».

این ماژول عمداً هیچ وابستگی‌ای از هیچ سرویسِ Core (قیمت‌گذاری/سفارش/
مشتری/انبار) به خودش ندارد و هیچ سرویسِ Coreای هم به این وابسته نیست --
حذفِ کاملِ این فایل هیچ تاثیری رویِ ERP یا موبایل ندارد (طبقِ اصلِ
صریحِ «AI Logic با Business Logic اصلی مخلوط نشود»).

فعال/غیرفعال‌بودن فعلاً یک سوییچِ سطحِ کد است (SMART_SALES_ENABLED)، نه
یک ردیفِ تازه در دیتابیس -- طبقِ اصلِ «Database را بی‌دلیل تغییر نده»؛
وقتی مدلِ واقعی (داخلی/بیرونی) وصل شد، این سوییچ به یک تنظیمِ
per-company (احتمالاً هم‌الگو با comm.ai_content_settings موجود -- که
از قبل کلیدِ APIِ هوشِ‌مصنوعیِ هر شرکت را نگه می‌دارد) تبدیل می‌شود."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ReorderSuggestion:
    item_id: int
    reason: str
    confidence: float  # ۰ تا ۱


class SmartSalesProvider(Protocol):
    """رابطِ ثابتی که هر پیاده‌سازیِ آینده (مدلِ داخلی/API بیرونی مثلِ
    OpenAI/Gemini/مدلِ آماری) باید همین را پیاده کند -- لایه‌هایِ بالادست
    (API/UI) فقط با همین Protocol کار می‌کنند، نه با پیاده‌سازیِ خاص."""

    def suggest_reorder_items(self, company_id: int, customer_detail_account_id: int) -> list[ReorderSuggestion]: ...

    def detect_churn_risk(self, company_id: int, customer_detail_account_id: int) -> float: ...


class NullSmartSalesProvider:
    """پیاده‌سازیِ پیش‌فرض -- طبقِ «فقط Architecture آماده باشد»: همیشه
    نتیجه‌یِ خالی/خنثی برمی‌گرداند. هر صفحه‌ای که این را صدا می‌زند باید
    حالتِ خالی را هم‌الگو با هر EmptyStateِ دیگر مدیریت کند."""

    def suggest_reorder_items(self, company_id: int, customer_detail_account_id: int) -> list[ReorderSuggestion]:
        return []

    def detect_churn_risk(self, company_id: int, customer_detail_account_id: int) -> float:
        return 0.0


SMART_SALES_ENABLED = False


def is_smart_sales_enabled() -> bool:
    return SMART_SALES_ENABLED


def get_smart_sales_provider() -> SmartSalesProvider:
    return NullSmartSalesProvider()
