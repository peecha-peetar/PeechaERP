"""فهرستِ فرم‌هایی که قابلیتِ «چند گزارشِ نام‌گذاری‌شده» را پشتیبانی
می‌کنند -- برایِ افزودنِ فرمِ جدید کافی است یک قالبِ پایه (jrxml) در
templates/ اضافه شود و یک ردیف این‌جا تعریف شود؛ نیازی به migration
نیست (ر.ک. توضیحِ 098_report_template_registry.sql)."""

from __future__ import annotations

FORM_DEFINITIONS: dict[str, dict[str, str]] = {
    "ITEM_LEDGER": {"label": "کاردکسِ کالا", "base_template": "kardex.jrxml"},
    "COMMERCIAL_INVOICE": {"label": "فاکتور / سندِ بازرگانی", "base_template": "invoice.jrxml"},
    "TRIAL_BALANCE": {"label": "تراز آزمایشی", "base_template": "trial_balance.jrxml"},
}
