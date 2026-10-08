"""اتصال ماژول‌های پیچا به موتور گردش کار (R295).

هر فایل برای یک ماژول: Adapter (فیلدهای شرط، اطلاعات تصمیم، اقدام‌ها روی همان سرویس‌های موجود)، مشاهدهٔ تغییر وضعیت
مدل‌ها (رویداد خودکار) و بررسی‌های دوره‌ای. هیچ منطق کسب‌وکاری این‌جا تکرار نمی‌شود.
"""

from peecha.services.workflow.adapters import commerce, crm, finance, fixed_assets, hr, inventory, production  # noqa: F401
