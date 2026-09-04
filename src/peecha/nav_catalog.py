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
            # طبقِ درخواستِ صریح («هر دریافت و پرداخت رفرنسِ فاکتور را
            # داشته باشد و مدیریتِ تسویه‌یِ فاکتورها را ایجاد کن»): تخصیصِ
            # (بخشی از) یک سندِ دریافت/پرداختِ ثبت‌شده به یک یا چند فاکتورِ
            # بازِ فروش/خرید.
            # طبقِ درخواستِ صریح («فرمِ تسویه‌یِ فاکتورهایِ خرید و فروش جدا از
            # هم باشه»): یک آیتمِ مشترک قبلاً هردو را با هم نشان می‌داد.
            {"code": "TREASURY_SETTLEMENT_SALES", "label": "تسویه‌یِ فاکتورهایِ فروش", "screen": "commercial_invoice_settlement_sales"},
            {"code": "TREASURY_SETTLEMENT_PURCHASE", "label": "تسویه‌یِ فاکتورهایِ خرید", "screen": "commercial_invoice_settlement_purchase"},
            # طبقِ درخواستِ صریح («روشِ دریافت/پرداختِ اقساطی»): دیدِ کلیِ
            # همه‌یِ اقساطِ برنامه‌ریزی‌شده -- خودِ دریافت/پرداخت از فرمِ
            # بالا (دکمه‌یِ 🔗) انجام می‌شود.
            {"code": "TREASURY_INSTALLMENTS", "label": "مدیریتِ اقساط", "screen": "installments_list"},
            # طبقِ ساختارِ واقعیِ تنخواه‌گردان: هر تنخواه‌دار (تفصیلیِ سطحِ
            # آخرِ گروهِ «تنخواه») چند تنخواهِ باز با شماره‌یِ خودکارِ
            # مستقل می‌تواند داشته باشد.
            {"code": "TREASURY_PETTY_CASH", "label": "تنخواه‌گردان", "screen": "treasury_petty_cash"},
            {"code": "TREASURY_PETTY_CASH_LIST", "label": "اسنادِ تنخواه‌گردان", "screen": "treasury_petty_cash_list"},
            {"code": "TREASURY_CHECKS_RECEIVED", "label": "چک‌هایِ دریافتی", "screen": "treasury_checks_received"},
            {"code": "TREASURY_CHECKS_ISSUED", "label": "چک‌هایِ پرداختی", "screen": "treasury_checks_issued"},
            {"code": "TREASURY_CHECKS_DUE", "label": "گزارشِ چک‌هایِ درجریانِ وصول", "screen": "treasury_checks_due"},
            # طبقِ درخواستِ صریح: گزارشِ عمومیِ چک‌ها (نه فقط درجریانِ وصول) —
            # فیلترِ نوع/سررسید/تاریخِ دریافت‌وصدور/طرفِ‌حساب/وضعیت/بانک + چاپ.
            {"code": "TREASURY_CHECKS_REPORT", "label": "گزارشِ چک‌ها", "screen": "report_checks"},
            # طبقِ آیتمِ ۵ («مغایرتِ بانکی/حساب از اکسل، فقط نمایشِ
            # اختلاف‌ها»): مقایسه‌یِ صورت‌حسابِ اکسلِ بانک با گردشِ همان
            # حساب در دفتر — بدونِ مکانیزمِ تطبیق‌دادنِ دستی.
            {"code": "TREASURY_RECONCILIATION", "label": "مغایرتِ بانکی/حساب", "screen": "bank_reconciliation"},
        ],
    },
    {
        "code": "INV",
        "label": "انبار و موجودی",
        "children": [
            # طبقِ ادغامِ فرمِ «کالا و خدمت» در گروهِ تفصیلیِ INVENTORY_ITEM:
            # صفحه‌یِ مستقلِ inventory_items.py حذف شد — تعریفِ/ویرایشِ کالا
            # حالا از طریقِ «تعریفِ تفصیلی» (GL_DIM) با انتخابِ گروهِ «کالا»
            # انجام می‌شود، دقیقاً هم‌الگو با ادغامِ پیشینِ HR_EMPLOYEES.
            {"code": "INV_WAREHOUSES", "label": "انبارها", "screen": "inventory_warehouses"},
            {"code": "INV_DOCUMENTS_LIST", "label": "اسنادِ انبار", "screen": "inventory_documents_list"},
            {"code": "INV_RECEIPT", "label": "رسید", "screen": "inventory_document_receipt"},
            {"code": "INV_ISSUE", "label": "حواله", "screen": "inventory_document_issue"},
            {"code": "INV_TRANSFER", "label": "انتقال", "screen": "inventory_document_transfer"},
            {"code": "INV_RETURN_IN", "label": "برگشت از فروش", "screen": "inventory_document_return_in"},
            {"code": "INV_RETURN_OUT", "label": "برگشت به تامین‌کننده", "screen": "inventory_document_return_out"},
            {"code": "INV_ADJUSTMENT", "label": "اصلاحِ موجودی", "screen": "inventory_document_adjustment"},
            # طبقِ درخواستِ صریح («فاکتورِ امانی -- هردو جهت»): دیدِ کلیِ
            # مانده‌یِ همه‌یِ اسنادِ امانیِ بازِ خروجی/ورودی + بازگردانیِ
            # کالایِ فروخته‌نشده/مصرف‌نشده (تسویه‌یِ واقعی از طریقِ همان
            # دکمه‌یِ «تبدیل به فاکتور» در خودِ فرمِ سند انجام می‌شود).
            {"code": "INV_CONSIGNMENT_TRACKING", "label": "پیگیریِ امانی", "screen": "commercial_consignment_tracking"},
        ],
    },
    {
        "code": "SALES",
        "label": "فروش و بازاریابی",
        "children": [
            # طبقِ درخواستِ صریح («دستیارِ فروش داخلِ ERP»): فهرستِ رتبه‌بندی‌
            # شده‌یِ مهم‌ترین اقداماتِ امروز (ریسکِ ریزش/فروشِ مکمل/رشدِ مشتری).
            {"code": "SALES_ASSISTANT", "label": "دستیارِ فروش", "screen": "sales_assistant"},
            {"code": "SALES_ORDER", "label": "سفارشِ فروش", "screen": "commercial_document_sales_order"},
            {"code": "SALES_PROFORMA", "label": "پیش‌فاکتورِ فروش", "screen": "commercial_document_sales_proforma"},
            {"code": "SALES_INVOICE", "label": "فاکتورِ فروش", "screen": "commercial_document_sales_invoice"},
            {"code": "SALES_RETURN", "label": "برگشت از فروش", "screen": "commercial_document_sales_return"},
            # طبقِ درخواستِ صریح («فاکتورِ امانی -- هردو جهت»): امانیِ
            # خروجی از نظرِ طرفِ‌حساب هم‌الگویِ فروش است.
            {"code": "SALES_CONSIGNMENT_OUT", "label": "امانیِ خروجی", "screen": "commercial_document_consignment_out"},
            {"code": "SALES_DOCUMENTS_LIST", "label": "اسنادِ فروش", "screen": "commercial_documents_list_sales"},
            {"code": "SALES_PRICING", "label": "فهرستِ قیمت و تخفیف", "screen": "commercial_pricing"},
            {"code": "SALES_POS_SESSIONS", "label": "ترمینال‌ها و جلسه‌هایِ صندوق", "screen": "commercial_pos_sessions"},
            {"code": "SALES_POS_SALE", "label": "فروشِ حضوری (POS)", "screen": "commercial_pos_sale"},
            {"code": "SALES_ECOMMERCE", "label": "فروشِ اینترنتی و Omnichannel", "screen": "commercial_ecommerce"},
            {"code": "SALES_AFTERSALES", "label": "خدماتِ پس‌ازفروش و گارانتی", "screen": "commercial_aftersales"},
        ],
    },
    {
        "code": "PURCH",
        "label": "خرید و تدارکات",
        "children": [
            {"code": "PURCH_ORDER", "label": "سفارشِ خرید", "screen": "commercial_document_purchase_order"},
            {"code": "PURCH_PROFORMA", "label": "پیش‌فاکتورِ خرید", "screen": "commercial_document_purchase_proforma"},
            {"code": "PURCH_INVOICE", "label": "فاکتورِ خرید", "screen": "commercial_document_purchase_invoice"},
            {"code": "PURCH_RETURN", "label": "برگشت به تامین‌کننده", "screen": "commercial_document_purchase_return"},
            # طبقِ درخواستِ صریح («فاکتورِ امانی -- هردو جهت»): امانیِ
            # ورودی از نظرِ طرفِ‌حساب هم‌الگویِ خرید است.
            {"code": "PURCH_CONSIGNMENT_IN", "label": "امانیِ ورودی", "screen": "commercial_document_consignment_in"},
            {"code": "PURCH_DOCUMENTS_LIST", "label": "اسنادِ خرید", "screen": "commercial_documents_list_purchase"},
            {"code": "PURCH_EXTRAS", "label": "ریبیتِ تامین‌کننده", "screen": "commercial_purchasing_extras"},
            # طبقِ درخواستِ صریح («زیرماژولِ مدیریتِ سفارشات»): پیگیریِ
            # پرداخت‌هایِ سفارشاتِ در راه (ترخیص/بهایِ اولیهٔ کالا و...) با
            # همان فرمِ دریافت/پرداختِ خزانه‌داری.
            {"code": "PURCH_ORDER_TRACKING", "label": "مدیریتِ سفارشات", "screen": "order_tracking"},
        ],
    },
    {
        "code": "HR",
        "label": "منابع انسانی",
        "children": [
            {"code": "HR_ORG_UNITS", "label": "واحدهایِ سازمانی", "screen": "hr_org_units"},
            {"code": "HR_JOB_GRADES", "label": "رده‌هایِ شغلی", "screen": "hr_job_grades"},
            {"code": "HR_POSITIONS", "label": "پست‌هایِ سازمانی", "screen": "hr_positions"},
            {"code": "HR_PAYROLL_RUN", "label": "اجرایِ محاسبهٔ حقوق", "screen": "payroll_run"},
            {"code": "HR_PAYROLL_LOANS", "label": "وام و مساعده", "screen": "payroll_loans"},
            # طبقِ یکپارچه‌سازیِ «تعریفِ کارمند فقط از طریقِ تفصیلی»: آیتمِ
            # مستقلِ HR_EMPLOYEES حذف شد (فرمِ تعریفِ کارمند دیگر detail_dimensions
            # است)؛ به‌جایش، ثبت/تاییدِ ساعاتِ اضافه‌کاری این‌جا اضافه شده.
            {"code": "HR_PAYROLL_OVERTIME", "label": "اضافه‌کاری", "screen": "payroll_overtime_entries"},
            # طبقِ گزارشِ صریح («فرمِ ورود و خروجِ کارمندان و فرمِ خلاصهٔ کارکرد
            # نداره»): حضوروغیابِ واقعیِ روزانه، مستقل از ثبتِ ساعاتِ اضافه‌کاری.
            {"code": "HR_ATTENDANCE_ENTRIES", "label": "ورود و خروجِ کارکنان", "screen": "hr_attendance_entries"},
            {"code": "HR_ATTENDANCE_SUMMARY", "label": "خلاصهٔ کارکرد", "screen": "hr_attendance_summary"},
            # طبقِ درخواستِ صریح: تنظیماتِ حقوق‌ودستمزد از یک آیتمِ مستقل به
            # تبی درونِ «تنظیماتِ سیستم» منتقل شد (هم‌الگو با نگاشتِ
            # صورت‌هایِ مالی) — دسترسی از طریقِ آیکونِ چرخ‌دنده‌یِ همین گروه
            # (_SETTINGS_TAB_BY_GROUP_CODE در shell_window.py).
        ],
    },
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
                    {
                        "code": "REPORTS_COST_CENTER",
                        "label": "گزارشِ مرکزِ هزینه و پروژه",
                        "screen": "report_cost_center_breakdown",
                    },
                ],
            },
            {
                "code": "REPORTS_INV",
                "label": "انبار",
                "children": [
                    {"code": "REPORTS_ITEM_LEDGER", "label": "کاردکسِ کالا", "screen": "report_item_ledger"},
                ],
            },
        ],
    },
    # این آیتم قبلاً یک گروهِ ۹-فرزندی بود؛ حالا همه‌ی آن فرم‌ها به‌صورتِ
    # تب‌هایِ سازمان‌یافته درونِ یک صفحه‌ی واحد («system_settings») جمع شده‌اند.
    {"code": "SETTINGS", "label": "تنظیمات سیستم", "screen": "system_settings"},
    # طبقِ گزارشِ صریح («بک‌آپِ قدیمی جدول‌هایِ تازه را نداشت»): ابزارِ
    # بک‌آپ/بازیابی — چون کاری/عملیاتی است (فایل‌دیالوگ، نه فرمِ ذخیره‌ای)،
    # به‌جایِ تبی درونِ system_settings، آیتمِ مستقلِ خودش را دارد.
    {"code": "SYSTEM_BACKUP", "label": "پشتیبان‌گیری و بازیابی", "screen": "system_backup"},
    # ابزارِ فنی/محدود (نه ویژگیِ عمومی) — طبقِ درخواستِ صریح: خام‌کردنِ
    # اطلاعاتِ شرکتِ جاری برایِ تست/راه‌اندازیِ اولیه، بدونِ تاثیر بر
    # ساختارِ برنامه یا سایرِ شرکت‌ها.
    {"code": "SYSTEM_DATA_RESET", "label": "خام‌کردنِ اطلاعات (فنی)", "screen": "system_data_reset"},
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
        # طبقِ گزارشِ صریح («هر فرم آیکنِ اختصاصیِ خودش را داشته باشد»):
        # این آیتم در ریبونِ حسابداری جا افتاده بود.
        ("GL_DIM_CONFIG", "🧩"),
    ],
    "TREASURY": [
        ("TREASURY_RECEIPT", "💵"),
        ("TREASURY_PAYMENT", "💸"),
        ("TREASURY_LIST", "📚"),
        ("TREASURY_SETTLEMENT_SALES", "🔗"),
        ("TREASURY_SETTLEMENT_PURCHASE", "🔁"),
        ("TREASURY_INSTALLMENTS", "📆"),
        ("TREASURY_PETTY_CASH", "👛"),
        ("TREASURY_PETTY_CASH_LIST", "🧾"),
        ("TREASURY_CHECKS_RECEIVED", "📥"),
        ("TREASURY_CHECKS_ISSUED", "📤"),
        ("TREASURY_CHECKS_DUE", "⏰"),
        ("TREASURY_CHECKS_REPORT", "📋"),
        ("TREASURY_RECONCILIATION", "🧾"),
    ],
    # طبقِ گزارشِ صریح («هر ماژول ریبونِ مختصِ خودش و هر فرم آیکنِ
    # اختصاصیِ خودش را داشته باشد»): این سه ماژول قبلاً فهرستِ خالی
    # داشتند — یعنی تا وقتی کاربر خودش با دکمه‌یِ ⚙ میان‌بر اضافه نمی‌کرد،
    # هیچ ریبونی نمی‌دید. حالا مثلِ GL/TREASURY/HR، همه‌یِ فرم‌هایِ برگِ
    # هر ماژول با یک آیکنِ اختصاصی پیش‌فرض نشان داده می‌شوند.
    "INV": [
        ("INV_WAREHOUSES", "🏬"),
        ("INV_DOCUMENTS_LIST", "📚"),
        ("INV_RECEIPT", "📥"),
        ("INV_ISSUE", "📤"),
        ("INV_TRANSFER", "🔄"),
        ("INV_RETURN_IN", "↩️"),
        ("INV_RETURN_OUT", "↪️"),
        ("INV_ADJUSTMENT", "🛠️"),
        ("INV_CONSIGNMENT_TRACKING", "🤝"),
    ],
    "SALES": [
        ("SALES_ASSISTANT", "🧠"),
        ("SALES_ORDER", "📝"),
        ("SALES_INVOICE", "🧾"),
        ("SALES_RETURN", "↩️"),
        ("SALES_CONSIGNMENT_OUT", "🤝"),
        ("SALES_DOCUMENTS_LIST", "📚"),
        ("SALES_PRICING", "🏷️"),
        ("SALES_POS_SESSIONS", "🖥️"),
        ("SALES_POS_SALE", "🛒"),
        ("SALES_ECOMMERCE", "🌐"),
        ("SALES_AFTERSALES", "🎧"),
    ],
    "PURCH": [
        ("PURCH_ORDER", "📝"),
        ("PURCH_INVOICE", "🧾"),
        ("PURCH_RETURN", "↪️"),
        ("PURCH_CONSIGNMENT_IN", "🤝"),
        ("PURCH_DOCUMENTS_LIST", "📚"),
        ("PURCH_EXTRAS", "🚢"),
    ],
    "HR": [
        ("HR_ORG_UNITS", "🏢"),
        ("HR_POSITIONS", "🗂️"),
        ("HR_JOB_GRADES", "🎖️"),
        ("HR_PAYROLL_RUN", "🧮"),
        ("HR_PAYROLL_LOANS", "🏦"),
        ("HR_PAYROLL_OVERTIME", "⏱️"),
        ("HR_ATTENDANCE_ENTRIES", "🕒"),
        ("HR_ATTENDANCE_SUMMARY", "📋"),
    ],
    "INVOICES": [],
    "REPORTS": [
        ("REPORTS_TRIAL_BALANCE", "⚖️"),
        ("REPORTS_JOURNAL_BOOK", "📖"),
        ("REPORTS_ACCOUNT_LEDGER", "📒"),
        ("REPORTS_INCOME_STATEMENT", "📈"),
        ("REPORTS_BALANCE_SHEET", "📊"),
        # طبقِ گزارشِ صریح («هر فرم آیکنِ اختصاصیِ خودش را داشته باشد»):
        # این ۷ گزارش قبلاً در ریبون نبودند — فقط از طریقِ دکمه‌یِ ⚙
        # با آیکنِ عمومیِ 📄 قابل‌اضافه‌شدن بودند.
        ("REPORTS_CASH_FLOW", "🌊"),
        ("REPORTS_EQUITY_CHANGES", "🏛️"),
        ("REPORTS_CUSTOM_STATEMENT", "🧩"),
        ("REPORTS_STATEMENT_DESIGNER", "🎨"),
        ("REPORTS_FINANCIAL_RATIOS", "➗"),
        ("REPORTS_PERIOD_COMPARISON", "🔀"),
        ("REPORTS_ANOMALIES", "⚠️"),
        ("REPORTS_COST_CENTER", "🏗️"),
        ("REPORTS_ITEM_LEDGER", "📋"),
    ],
    "SETTINGS": [],
}

# صفحاتی که در NAV_ITEMS نیامده‌اند چون به‌صورتِ زیرتب/زیرزیرتبِ «تنظیماتِ
# سیستم» (system_settings.py) درونِ یک صفحه‌ی واحد جمع شده‌اند — این‌ها هم
# باید در جدولِ دسترسیِ نقش‌ها قابلِ‌تنظیم باشند.
SETTINGS_SUB_FORMS = [
    ("accounting_coding", "کدینگِ حساب‌ها"),
    ("detail_level_digits", "تعدادِ رقمِ سطوحِ تفصیلی"),
    ("financial_statement_mapping", "تنظیماتِ صورت‌هایِ مالی"),
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
    ("payroll_settings", "تنظیماتِ حقوق و دستمزد"),
]

# نگاشتِ کدِ ماژولِ آیتم‌هایِ سطحِ بالایی که خودشان زیرگروه ندارند — فقط
# «داشبورد» با این قاعده مچ نمی‌شود (کدِ خودش با کدِ ماژولش یکی نیست).
_TOP_LEVEL_MODULE_CODE_OVERRIDE = {
    "dashboard": "DASH",
    "SYSTEM_BACKUP": "SETTINGS",
    "SYSTEM_DATA_RESET": "SETTINGS",
}


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
