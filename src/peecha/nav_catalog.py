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
    # طبقِ درخواستِ صریح («سیستمِ کارتابل قابلِ‌گسترش برایِ همه‌یِ ماژول‌ها»):
    # این آیتم عمداً بالایِ ساید‌بار و مستقلِ از هر ماژول است — کارتابل هر
    # کاربر می‌تواند هم‌زمان اقلامی از حسابداری/خزانه‌داری/هر ماژولِ دیگر
    # داشته باشد، پس زیرِ هیچ‌کدام قرار نمی‌گیرد (services/cartable.py).
    {"code": "MY_TASKS", "label": "کارتابلِ من", "screen": "my_tasks"},
    {
        "code": "GL",
        "label": "مالی و حسابداری",
        "children": [
            {"code": "GL_COA", "label": "کدینگ حسابداری", "screen": "chart_of_accounts"},
            # طبقِ درخواستِ صریح: تعریفِ همه‌یِ حساب‌هایِ تفصیلی (مشتری/
            # تامین‌کننده/پرسنل، کالا/بانک/صندوق/تنخواه/دارایی‌ثابت/مرکزِ
            # هزینه/پروژه، و گروه‌هایِ سفارشی) حالا در یک فرمِ واحد است —
            # به‌جایِ منویِ جداگانه برایِ هرکدام، از هدرِ همان یک فرم
            # («تعریفِ تفصیلی») نوعِ گروه انتخاب می‌شود.
            {"code": "GL_TAFSILI", "label": "تفصیلی‌ها", "screen": "detail_accounts_list", "in_ribbon": False},
            {"code": "GL_JE_LIST", "label": "اسناد حسابداری", "screen": "journal_entries_list"},
            {"code": "GL_JE", "label": "صدور سند جدید", "screen": "journal_entry"},
            {"code": "GL_DIM_CONFIG", "label": "پیکربندیِ گروه‌هایِ تفصیلی", "screen": "dimension_group_config", "in_ribbon": False},
            {"code": "GL_DIM", "label": "تعریفِ تفصیلی", "screen": "detail_dimensions", "in_ribbon": False},
        ],
    },
    {
        "code": "TREASURY",
        "label": "خزانه‌داری",
        "children": [
            # طبقِ طرحِ تاییدشده (فازِ ۲): فرمِ دریافت/پرداخت حالا چندروشی
            # است (نقد/بانک/چک/تخفیف در یک سند) — هر ردیف طبقِ نگاشتِ
            # حساب‌هایِ تنظیماتِ خزانه‌داری خودکار به حسابِ کلِ خودش می‌رود.
            {"code": "TREASURY_RECEIPT", "label": "سندِ دریافت", "screen": "treasury_voucher_receipt"},
            {"code": "TREASURY_PAYMENT", "label": "سندِ پرداخت", "screen": "treasury_voucher_payment"},
            {"code": "TREASURY_LIST", "label": "اسنادِ خزانه‌داری", "screen": "treasury_vouchers_list"},
            {"code": "TREASURY_CHECKS_RECEIVED", "label": "چک‌هایِ دریافتی", "screen": "treasury_checks_received"},
            {"code": "TREASURY_CHECKS_ISSUED", "label": "چک‌هایِ پرداختی", "screen": "treasury_checks_issued"},
            {"code": "TREASURY_CHECKS_DUE", "label": "گزارشِ چک‌هایِ درجریانِ وصول", "screen": "treasury_checks_due"},
            {"code": "TREASURY_SETTINGS", "label": "تنظیماتِ خزانه‌داری", "screen": "treasury_settings", "in_ribbon": False},
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
        # طبقِ درخواستِ صریح: هر ماژول باید فقط یک آیتم زیرِ «گزارش‌ها»
        # داشته باشد و بقیه‌یِ گزارش‌هایِ همان ماژول زیرِ همان یک آیتم
        # (مثلِ «حسابداری») بیایند — تا فهرست شلوغ/تخت نباشد. امروز فقط
        # ماژولِ مالی‌وحسابداری گزارش دارد؛ وقتی گزارش‌هایِ ماژول‌هایِ
        # دیگر (فروش/انبار/...) ساخته شوند، هرکدام زیرمنویِ جداگانه‌یِ
        # خودشان را این‌جا می‌گیرند.
        "children": [
            {
                "code": "REPORTS_GL",
                "label": "حسابداری",
                "children": [
                    {"code": "REPORTS_TRIAL_BALANCE", "label": "تراز آزمایشی", "screen": "report_trial_balance"},
                    {"code": "REPORTS_JOURNAL_BOOK", "label": "دفتر روزنامه", "screen": "report_journal_book"},
                    {
                        "code": "REPORTS_ACCOUNT_LEDGER",
                        "label": "دفتر کل / معین / تفصیلی",
                        "screen": "report_account_ledger",
                    },
                    {
                        "code": "REPORTS_INCOME_STATEMENT",
                        "label": "صورتِ سود و زیان",
                        "screen": "report_income_statement",
                    },
                    {"code": "REPORTS_BALANCE_SHEET", "label": "ترازنامه", "screen": "report_balance_sheet"},
                    {"code": "REPORTS_CASH_FLOW", "label": "صورتِ گردشِ وجوهِ نقد", "screen": "report_cash_flow"},
                    {
                        "code": "REPORTS_EQUITY_CHANGES",
                        "label": "تغییرات در حقوقِ صاحبانِ سهام",
                        "screen": "report_equity_changes",
                    },
                    {
                        "code": "REPORTS_CUSTOM_STATEMENT",
                        "label": "گزارشِ سفارشی (طبقِ الگو)",
                        "screen": "report_custom_statement",
                    },
                    {
                        "code": "REPORTS_STATEMENT_DESIGNER",
                        "label": "طراحیِ الگویِ گزارش",
                        "screen": "statement_template_designer",
                    },
                    {
                        "code": "REPORTS_FINANCIAL_RATIOS",
                        "label": "نسبت‌هایِ مالی",
                        "screen": "report_financial_ratios",
                    },
                    {
                        "code": "REPORTS_PERIOD_COMPARISON",
                        "label": "مقایسه‌یِ دوره‌ای",
                        "screen": "report_period_comparison",
                    },
                    {
                        "code": "REPORTS_ANOMALIES",
                        "label": "تشخیصِ سندهایِ ناقص/آنومالی",
                        "screen": "report_anomalies",
                    },
                ],
            },
        ],
    },
    # این آیتم قبلاً یک گروهِ ۹-فرزندی بود؛ حالا همه‌ی آن فرم‌ها به‌صورتِ
    # تب‌هایِ سازمان‌یافته درونِ یک صفحه‌ی واحد («system_settings») جمع شده‌اند.
    {"code": "SETTINGS", "label": "تنظیمات سیستم", "screen": "system_settings"},
]

# طبقِ درخواستِ صریح («ریبونِ بالا مرتبط با ماژولی باشد که در ساید‌بار
# بازش کرده‌ایم، و هر ماژول ریبونِ مختصِ خودش را داشته باشد، با قابلیتِ
# کم‌وزیادکردنِ دکمه‌ها»): برخلافِ نسخه‌یِ قبلی (یک فهرستِ ثابتِ سراسری)،
# حالا این یک دیکشنری‌یِ کدِ ماژول → فهرستِ میان‌برهایِ *پیش‌فرضِ* همان
# ماژول است. shell_window.py با بازشدنِ هر صفحه، ماژولِ آن را تشخیص
# می‌دهد و ریبون را با میان‌برهایِ همان ماژول (پیش‌فرض، یا شخصی‌سازیِ
# کاربر که در QSettings ذخیره می‌شود) دوباره می‌سازد. دکمه‌یِ ⚙ در انتهایِ
# ریبون امکانِ تیک‌زدن/بردا‌شتنِ هرکدام از آیتم‌هایِ همان ماژول را می‌دهد.
DEFAULT_QUICK_ACCESS_BY_MODULE: dict[str, list[tuple[str, str]]] = {
    "dashboard": [],
    "MY_TASKS": [],
    "GL": [
        ("GL_JE", "📝"),
        ("GL_COA", "🗂️"),
        ("GL_JE_LIST", "📚"),
        ("GL_TAFSILI", "🤝"),
        ("GL_DIM", "🧰"),
    ],
    "TREASURY": [
        ("TREASURY_RECEIPT", "💵"),
        ("TREASURY_PAYMENT", "💸"),
        ("TREASURY_LIST", "📚"),
        ("TREASURY_CHECKS_RECEIVED", "📥"),
        ("TREASURY_CHECKS_ISSUED", "📤"),
        ("TREASURY_CHECKS_DUE", "⏰"),
    ],
    "INV": [],
    "SALES": [],
    "PURCH": [],
    "HR": [],
    "INVOICES": [],
    "REPORTS": [
        ("REPORTS_TRIAL_BALANCE", "⚖️"),
        ("REPORTS_JOURNAL_BOOK", "📖"),
        ("REPORTS_ACCOUNT_LEDGER", "📒"),
        ("REPORTS_INCOME_STATEMENT", "📈"),
        ("REPORTS_BALANCE_SHEET", "📊"),
    ],
    "SETTINGS": [],
}

# صفحاتی که در NAV_ITEMS نیامده‌اند چون به‌صورتِ زیرتب/زیرزیرتبِ «تنظیماتِ
# سیستم» (system_settings.py) درونِ یک صفحه‌ی واحد جمع شده‌اند — این‌ها هم
# باید در جدولِ دسترسیِ نقش‌ها قابلِ‌تنظیم باشند.
SETTINGS_SUB_FORMS = [
    ("accounting_coding", "کدینگِ حساب‌ها"),
    ("detail_level_digits", "تعدادِ رقمِ سطوحِ تفصیلی"),
    ("financial_statement_mapping", "نگاشتِ صورت‌هایِ مالی"),
    ("companies", "شرکت‌ها"),
    ("languages", "زبان‌ها"),
    ("currencies", "ارزها"),
    ("fiscal_years", "سال‌های مالی"),
    ("users", "کاربران"),
    ("roles", "نقش‌ها و دسترسی‌ها"),
    ("field_labels", "عنوانِ فیلدها"),
    ("translations", "ترجمه‌ها"),
    ("workflow_designer", "طراحیِ گردشِ کار"),
    ("audit_log", "امنیت (رخدادنگار)"),
]

# نگاشتِ کدِ ماژولِ آیتم‌هایِ سطحِ بالایی که خودشان زیرگروه ندارند — فقط
# «داشبورد» با این قاعده مچ نمی‌شود (کدِ خودش با کدِ ماژولش یکی نیست).
_TOP_LEVEL_MODULE_CODE_OVERRIDE = {"dashboard": "DASH"}


def flatten_nav_items() -> list[dict]:
    """همه‌یِ آیتم‌هایِ برگ (دارایِ «screen») را، در هر عمقی از تودرتوییِ
    زیرمنوها، برمی‌گرداند — منویِ «گزارش‌ها» مثلاً حالا یک لایه‌یِ زیرمنویِ
    ماژول (مثلِ «حسابداری») هم دارد، پس بازگشتی طی می‌شود."""
    flat: list[dict] = []

    def _walk(items: list[dict]) -> None:
        for item in items:
            if item.get("children"):
                _walk(item["children"])
            else:
                flat.append(item)

    _walk(NAV_ITEMS)
    return flat


def build_form_catalog() -> list[tuple[str, str, str]]:
    """(form_code, module_code, label) برایِ همه‌ی صفحاتِ برنامه — از رویِ
    NAV_ITEMS + زیرتب‌هایِ «تنظیماتِ سیستم» — تکِ منبعِ حقیقتی که
    services/roles.py برایِ ساختِ جدولِ دسترسیِ نقش‌ها استفاده می‌کند.
    ماژولِ هر فرم همیشه کدِ آیتمِ سطحِ‌بالا است، حتی اگر خودِ فرم چند لایه
    زیرِ زیرمنوهایِ داخلی (مثلِ «گزارش‌ها ← حسابداری») تودرتو باشد."""
    catalog: list[tuple[str, str, str]] = []

    def _walk(items: list[dict], module_code: str) -> None:
        for item in items:
            if item.get("children"):
                _walk(item["children"], module_code)
            elif item.get("screen"):
                catalog.append((item["screen"], module_code, item["label"]))

    for item in NAV_ITEMS:
        if item.get("children"):
            _walk(item["children"], item["code"])
        elif item.get("screen"):
            module_code = _TOP_LEVEL_MODULE_CODE_OVERRIDE.get(item["code"], item["code"])
            catalog.append((item["screen"], module_code, item["label"]))
    for code, label in SETTINGS_SUB_FORMS:
        catalog.append((code, "SETTINGS", label))
    return catalog
