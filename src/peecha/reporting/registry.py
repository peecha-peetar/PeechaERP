"""فهرستِ فرم‌هایی که قابلیتِ «چند گزارشِ نام‌گذاری‌شده» را پشتیبانی
می‌کنند -- برایِ افزودنِ فرمِ جدید کافی است یک قالبِ پایه (jrxml) در
templates/ اضافه شود و یک ردیف این‌جا تعریف شود؛ نیازی به migration
نیست (ر.ک. توضیحِ 098_report_template_registry.sql)."""

from __future__ import annotations

FORM_DEFINITIONS: dict[str, dict[str, str]] = {
    "ITEM_LEDGER": {"label": "کاردکسِ کالا", "base_template": "kardex.jrxml"},
    "COMMERCIAL_INVOICE": {"label": "فاکتور / سندِ بازرگانی", "base_template": "invoice.jrxml"},
    # طبقِ درخواستِ صریح («نمونه فاکتورِ تک‌فروشی ایجاد بشه که از فاکتورِ
    # عمده مجزا باشه»): فرمِ کاملاً جداگانه -- قالبِ اولیه‌اش کپیِ همان
    # invoice.jrxml است، ولی از این پس مستقل و قابلِ‌ویرایشِ جداگانه (از
    # همین صفحه‌یِ «گزارش‌هایِ حرفه‌ای») است و هیچ تغییری رویِ نمونه‌یِ
    # فاکتورِ عمده اثر نمی‌گذارد.
    "POS_RECEIPT": {"label": "فاکتور/فیشِ تک‌فروشی (POS)", "base_template": "pos_receipt.jrxml"},
    "TRIAL_BALANCE": {"label": "تراز آزمایشی", "base_template": "trial_balance.jrxml"},
    "JOURNAL_BOOK": {"label": "دفترِ روزنامه", "base_template": "journal_book.jrxml"},
    # طبقِ اشتراکِ شکلِ ستونی: حالتِ «خلاصه»یِ دفترِ کل/معین/تفصیلی دقیقاً
    # همان جدولِ تراز آزمایشیِ ۶ ستونی است -- از همان قالبِ پایه شروع می‌شود.
    "ACCOUNT_LEDGER_SUMMARY": {"label": "دفترِ کل/معین/تفصیلی — خلاصه", "base_template": "trial_balance.jrxml"},
    "ACCOUNT_LEDGER_DETAIL": {"label": "دفترِ کل/معین/تفصیلی — گردشِ حساب", "base_template": "account_ledger_detail.jrxml"},
    "INCOME_STATEMENT": {"label": "صورتِ سود و زیان", "base_template": "income_statement.jrxml"},
    "BALANCE_SHEET": {"label": "ترازنامه", "base_template": "balance_sheet.jrxml"},
    "STOCK_DOCUMENT": {"label": "سندِ انبار (رسید/حواله/انتقال/برگشت/اصلاح)", "base_template": "stock_document.jrxml"},
}
