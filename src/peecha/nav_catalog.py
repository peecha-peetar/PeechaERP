"""فهرستِ متمرکزِ صفحاتِ برنامه — تکِ منبعِ حقیقتِ ناوبری (shell_window.py)
و کاتالوگِ فرم‌هایِ نقش‌ها/دسترسی‌ها (services/roles.py). طبقِ بازخوردِ
صریح: قبلاً roles.py یک فهرستِ دستیِ جداگانه (_FORMS) داشت که با اضافه‌شدنِ
صفحه‌هایِ تازه (در طولِ توسعه) به‌روز نمی‌شد و فرم‌های تازه هیچ‌وقت در جدولِ
دسترسیِ نقش‌ها ظاهر نمی‌شدند — حالا هر دو از همین‌جا می‌خوانند تا افزودنِ
یک آیتمِ تازه به NAV_ITEMS، به‌طورِ خودکار هم در ناوبری و هم در جدولِ
دسترسی‌ها ظاهر شود، بدونِ نگه‌داریِ دو فهرستِ جداگانه‌یِ هم‌پوشان."""

from __future__ import annotations

NAV_ITEMS = [
    {"code": "dashboard", "label": "داشبورد", "screen": "dashboard"},
    {
        "code": "GL",
        "label": "مالی و حسابداری",
        "children": [
            {"code": "GL_COA", "label": "کدینگ حسابداری", "screen": "chart_of_accounts"},
            # طبقِ درخواستِ صریح: انواعِ تفصیلی از ریبون حذف شدند (همچنان از
            # ساید‌بار در دسترس‌اند؛ دکمه‌ی «تفصیلیِ جدید» در خودِ صفحه‌ی
            # «تفصیلی‌ها» میان‌بُرِ ساختِ رکوردِ تازه برایِ هرکدام را می‌دهد) —
            # تا دکمه‌هایِ باقی‌مانده (کدینگ/اسناد/صدورِ سند) فضایِ بیشتری
            # داشته باشند و ریبون کمتر شلوغ باشد.
            {"code": "GL_TAFSILI", "label": "تفصیلی‌ها", "screen": "detail_accounts_list", "in_ribbon": False},
            {"code": "GL_CUSTOMERS", "label": "مشتریان", "screen": "customers", "in_ribbon": False},
            {"code": "GL_SUPPLIERS", "label": "تامین‌کنندگان", "screen": "suppliers", "in_ribbon": False},
            {"code": "GL_PERSONNEL", "label": "پرسنل", "screen": "personnel", "in_ribbon": False},
            {"code": "GL_INVENTORY_ITEMS", "label": "کالا", "screen": "inventory_items", "in_ribbon": False},
            {"code": "GL_FIXED_ASSETS", "label": "دارایی ثابت", "screen": "fixed_assets", "in_ribbon": False},
            {"code": "GL_BANK_ACCOUNTS", "label": "بانک", "screen": "bank_accounts", "in_ribbon": False},
            {"code": "GL_CASH_BOXES", "label": "صندوق", "screen": "cash_boxes", "in_ribbon": False},
            {"code": "GL_PETTY_CASHES", "label": "تنخواه", "screen": "petty_cashes", "in_ribbon": False},
            {"code": "GL_COST_CENTERS", "label": "مرکز هزینه", "screen": "cost_centers", "in_ribbon": False},
            {"code": "GL_PROJECTS", "label": "پروژه", "screen": "projects", "in_ribbon": False},
            {"code": "GL_JE_LIST", "label": "اسناد حسابداری", "screen": "journal_entries_list"},
            {"code": "GL_JE", "label": "صدور سند جدید", "screen": "journal_entry"},
            {"code": "GL_DIM_CONFIG", "label": "پیکربندیِ گروه‌هایِ تفصیلی", "screen": "dimension_group_config", "in_ribbon": False},
            {"code": "GL_DIM", "label": "تفصیلی‌هایِ گروه‌هایِ ساده", "screen": "detail_dimensions", "in_ribbon": False},
        ],
    },
    {"code": "INV", "label": "انبار و موجودی", "screen": None},
    {"code": "SALES", "label": "فروش و بازاریابی", "screen": None},
    {"code": "PURCH", "label": "خرید و تدارکات", "screen": None},
    {"code": "HR", "label": "منابع انسانی", "screen": None},
    {"code": "INVOICES", "label": "فاکتورها", "screen": None},
    {
        "code": "REPORTS",
        "label": "گزارش‌ها",
        "children": [
            {"code": "REPORTS_TRIAL_BALANCE", "label": "تراز آزمایشی", "screen": "report_trial_balance"},
            {"code": "REPORTS_JOURNAL_BOOK", "label": "دفتر روزنامه", "screen": "report_journal_book"},
            {
                "code": "REPORTS_ACCOUNT_LEDGER",
                "label": "دفتر کل / معین / تفصیلی",
                "screen": "report_account_ledger",
            },
            {"code": "REPORTS_INCOME_STATEMENT", "label": "صورتِ سود و زیان", "screen": "report_income_statement"},
            {"code": "REPORTS_BALANCE_SHEET", "label": "ترازنامه", "screen": "report_balance_sheet"},
            {"code": "REPORTS_CASH_FLOW", "label": "صورتِ گردشِ وجوهِ نقد", "screen": "report_cash_flow"},
            {
                "code": "REPORTS_EQUITY_CHANGES",
                "label": "تغییرات در حقوقِ صاحبانِ سهام",
                "screen": "report_equity_changes",
            },
        ],
    },
    # این آیتم قبلاً یک گروهِ ۹-فرزندی بود؛ حالا همه‌ی آن فرم‌ها به‌صورتِ
    # تب‌هایِ سازمان‌یافته درونِ یک صفحه‌ی واحد («system_settings») جمع شده‌اند.
    {"code": "SETTINGS", "label": "تنظیمات سیستم", "screen": "system_settings"},
]

# صفحاتی که در NAV_ITEMS نیامده‌اند چون به‌صورتِ زیرتب/زیرزیرتبِ «تنظیماتِ
# سیستم» (system_settings.py) درونِ یک صفحه‌ی واحد جمع شده‌اند — این‌ها هم
# باید در جدولِ دسترسیِ نقش‌ها قابلِ‌تنظیم باشند.
SETTINGS_SUB_FORMS = [
    ("accounting_coding", "کدینگِ حساب‌ها"),
    ("detail_level_digits", "تعدادِ رقمِ سطوحِ تفصیلی"),
    ("companies", "شرکت‌ها"),
    ("languages", "زبان‌ها"),
    ("currencies", "ارزها"),
    ("fiscal_years", "سال‌های مالی"),
    ("users", "کاربران"),
    ("roles", "نقش‌ها و دسترسی‌ها"),
    ("field_labels", "عنوانِ فیلدها"),
    ("translations", "ترجمه‌ها"),
    ("audit_log", "امنیت (رخدادنگار)"),
]

# نگاشتِ کدِ ماژولِ آیتم‌هایِ سطحِ بالایی که خودشان زیرگروه ندارند — فقط
# «داشبورد» با این قاعده مچ نمی‌شود (کدِ خودش با کدِ ماژولش یکی نیست).
_TOP_LEVEL_MODULE_CODE_OVERRIDE = {"dashboard": "DASH"}


def flatten_nav_items() -> list[dict]:
    flat: list[dict] = []
    for item in NAV_ITEMS:
        if "children" in item:
            flat.extend(item["children"])
        else:
            flat.append(item)
    return flat


def build_form_catalog() -> list[tuple[str, str, str]]:
    """(form_code, module_code, label) برایِ همه‌ی صفحاتِ برنامه — از رویِ
    NAV_ITEMS + زیرتب‌هایِ «تنظیماتِ سیستم» — تکِ منبعِ حقیقتی که
    services/roles.py برایِ ساختِ جدولِ دسترسیِ نقش‌ها استفاده می‌کند."""
    catalog: list[tuple[str, str, str]] = []
    for item in NAV_ITEMS:
        if "children" in item:
            for child in item["children"]:
                if child.get("screen"):
                    catalog.append((child["screen"], item["code"], child["label"]))
        elif item.get("screen"):
            module_code = _TOP_LEVEL_MODULE_CODE_OVERRIDE.get(item["code"], item["code"])
            catalog.append((item["screen"], module_code, item["label"]))
    for code, label in SETTINGS_SUB_FORMS:
        catalog.append((code, "SETTINGS", label))
    return catalog
