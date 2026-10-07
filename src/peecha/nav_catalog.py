"""فهرست متمرکز صفحات برنامه — تک منبع حقیقت ناوبری (shell_window.py)
و کاتالوگ فرم‌های نقش‌ها/دسترسی‌ها (services/roles.py). طبق بازخورد
صریح: قبلاً roles.py یک فهرست دستی جداگانه (_FORMS) داشت که با اضافه‌شدن
صفحه‌های تازه (در طول توسعه) به‌روز نمی‌شد و فرم‌های تازه هیچ‌وقت در جدول
دسترسی نقش‌ها ظاهر نمی‌شدند — حالا هر دو از همین‌جا می‌خوانند تا افزودن
یک آیتم تازه به NAV_ITEMS، به‌طور خودکار هم در ناوبری و هم در جدول
دسترسی‌ها ظاهر شود، بدون نگه‌داری دو فهرست جداگانهٔ هم‌پوشان."""

from __future__ import annotations

# R233/R236: منویِ «گزارش‌ها ‹ گزارشاتِ خرید» -- کدها هم‌نامِ services/purchase_reports.REPORTS (تست تطابق را بررسی می‌کند)
PURCHASE_REPORT_MENU = [
    ("DASH", "داشبوردها", [
        {"code": "PURCH_RPT_DASH_EXEC", "label": "داشبورد مدیریتی خرید", "screen": "purchase_dashboard_exec"},
        {"code": "PURCH_RPT_DASH_EXCEPTIONS", "label": "داشبورد استثناهای خرید", "screen": "purchase_dashboard_exceptions"},
    ]),
    ("OPS", "عملیاتی", [
        ("REG_INVOICE", "دفتر فاکتورهای خرید"), ("REG_INVOICE_LINES", "ریز اقلام فاکتورهای خرید"),
        ("REG_ORDER", "دفتر سفارش‌های خرید"), ("REG_PROFORMA", "دفتر پیش‌فاکتورهای خرید"),
        ("OPEN_PO", "سفارش‌های خرید باز"), ("OVERDUE", "کالاهای در راه / معوق"),
        ("PENDING_RECEIPTS", "رسیدهای در انتظار انبار"), ("GRIR", "رسیده ولی فاکتورنشده"),
        ("PENDING_INVOICES", "فاکتورهای خرید در انتظار"), ("CONSIGNMENTS", "امانی‌های ورودی تسویه‌نشده"),
        ("RETURNS", "برگشت به تامین‌کننده"), ("PARTIAL_RECEIPT", "سفارش‌های با دریافت ناقص"),
        ("NO_RECEIPT", "سفارش‌های بدون رسید"), ("NO_INVOICE", "سفارش‌های بدون فاکتور"),
        ("RECEIPT_MISMATCH", "رسیدهای دارای مغایرت"), ("CANCELLED", "اسناد خرید لغوشده"),
        ("CANCEL_ANALYSIS", "تحلیل علت‌های لغو"), ("EMERGENCY", "خریدهای اضطراری"),
    ]),
    ("REQUESTS", "درخواست خرید", [
        ("PR_REGISTER", "دفتر درخواست‌های خرید"), ("PR_PENDING", "درخواست‌های منتظر تصویب"),
        ("PR_NOT_ORDERED", "درخواست‌های تصویب‌شدهٔ بدون سفارش"), ("PR_CYCLE", "زمان چرخهٔ درخواست تا سفارش"),
        ("PR_BY_REQUESTER", "درخواست‌ها به تفکیک درخواست‌کننده/دپارتمان"), ("PR_REJECTED", "درخواست‌های ردشده/لغوشده"),
    ]),
    ("RFQ", "استعلام قیمت", [
        ("RFQ_REGISTER", "دفتر استعلام‌های قیمت"), ("RFQ_COMPARISON", "مقایسهٔ پیشنهادهای تامین‌کنندگان"),
        ("RFQ_SAVINGS", "صرفه‌جویی استعلام قیمت"), ("RFQ_PENDING", "پاسخ‌های معوق استعلام"),
    ]),
    ("BUDGET", "بودجهٔ خرید", [
        ("BUDGET_VS_ACTUAL", "بودجه در برابر واقعی و تعهد"), ("BUDGET_OVERRUN", "بودجه‌های نزدیک به سقف/عبورکرده"),
        ("BUDGET_BY_DIMENSION", "بودجه به تفکیک مرکز هزینه/پروژه/گروه"), ("BUDGET_MONTHLY", "روند ماهانهٔ بودجه"),
        ("BUDGET_ACTUALS", "ریز مصرف واقعی بودجه"), ("BUDGET_COMMITMENTS", "تعهدات بودجه (سفارش‌های باز)"),
        ("BUDGET_PIPELINE", "درخواست‌های در جریان بودجه"), ("BUDGET_FORECAST", "پیش‌بینی مصرف بودجه تا پایان دوره"),
        ("UNBUDGETED", "خرید خارج از بودجه"),
    ]),
    ("CONTROL", "کنترل و حسابرسی", [
        ("THREE_WAY", "تطبیق سه‌طرفه (سفارش/رسید/فاکتور)"), ("NO_PO", "خرید بدون سفارش"),
        ("INVOICE_NO_RECEIPT", "فاکتور بدون رسید"), ("INVOICE_OVER_PO", "فاکتور بیش از سفارش"),
        ("RECEIPT_OVER_PO", "رسید بیش از سفارش"), ("APPROVAL_PENDING", "اسناد منتظر تصویب مدیر"),
        ("DOC_TRAIL", "سابقهٔ تغییرات اسناد خرید"), ("USER_ACTIVITY", "فعالیت کاربران در خرید"),
        ("CHANGED_AFTER_APPROVAL", "تغییر قیمت/مقدار پس از تایید"), ("MODIFIED_DOCS", "اسناد اصلاح‌شده پس از تایید"),
        ("APPROVAL_HISTORY", "تاریخچهٔ تایید و تصویب"), ("SOD_VIOLATIONS", "تخلفات تفکیک وظایف"),
        ("PO_WITHOUT_PR", "سفارش خرید بدون درخواست"), ("PO_WITHOUT_RFQ", "خرید بدون استعلام رقابتی"),
        ("DUPLICATE_INVOICES", "فاکتورهای خرید احتمالاً تکراری"), ("EXPIRING_CONTRACTS", "قراردادهای خرید در آستانهٔ انقضا"),
    ]),
    ("PROCESS", "فرآیند خرید", [
        ("PO_FLOW", "گردش سفارش خرید"), ("CYCLE_TIME", "زمان چرخهٔ خرید"),
    ]),
    ("ANALYSIS", "تحلیل خرید", [
        ("BY_ITEM", "خرید به تفکیک کالا"), ("BY_SUPPLIER", "خرید به تفکیک تامین‌کننده"),
        ("BY_CATEGORY", "خرید به تفکیک گروه کالا"), ("BY_COST_CENTER", "خرید به تفکیک مرکز هزینه/پروژه"),
        ("MONTHLY", "روند ماهانهٔ خرید"), ("ABC", "تحلیل ABC خرید (پارتو)"),
        ("CONCENTRATION", "تمرکز تامین (ریسک تک‌منبعی)"), ("BY_DIMENSION", "خرید به تفکیک شعبه/دپارتمان/پروژه/برند/..."),
        ("PERIOD_COMPARE", "مقایسهٔ خرید با دورهٔ قبل"), ("SUPPLIER_SHARE", "سهم تامین‌کنندگان از هر کالا"),
        ("BY_CURRENCY", "خرید به تفکیک ارز"),
    ]),
    ("PRICE", "قیمت و هزینه", [
        ("PRICE_HISTORY", "تاریخچهٔ قیمت خرید"), ("PRICE_COMPARE", "مقایسهٔ قیمت تامین‌کنندگان"),
        ("PPV", "انحراف قیمت خرید"), ("CORRECTIONS", "اصلاحیه‌های فاکتور و مغایرت بها"),
        ("LANDED_COST", "هزینه‌های جانبی خرید"), ("SAVINGS", "تخفیف‌ها و تخفیف حجمی خرید"),
        ("PRICE_VS_REFERENCE", "خرید بالاتر/پایین‌تر از قیمت مرجع"), ("PRICE_MOVERS", "بیشترین افزایش/کاهش قیمت"),
        ("LANDED_BY_TYPE", "هزینه‌های جانبی به تفکیک نوع"), ("ACTUAL_COST", "بهای واقعی تامین"),
        ("LAST_PURCHASE", "آخرین خرید هر کالا"), ("PURCHASE_VS_SALE", "قیمت خرید در برابر فروش"),
    ]),
    ("VENDOR", "ارزیابی تامین‌کننده", [
        ("SCORECARD", "کارنامهٔ تامین‌کننده"), ("OTD", "تحویل به‌موقع"),
        ("FILL_RATE", "دقت مقدار تحویل تامین‌کنندگان"), ("QUALITY", "کیفیت / نرخ برگشت"),
        ("LEAD_TIME", "زمان تحویل"), ("PRICE_STABILITY", "ثبات قیمت تامین‌کننده"),
        ("LATE_ORDERS", "سفارش‌های دیرکرد"), ("INACTIVE_SUPPLIERS", "تامین‌کنندگان غیرفعال"),
        ("LINE_DELIVERY", "تحویل ردیفی سفارش‌ها"), ("RFQ_RESPONSE", "پاسخ‌گویی تامین‌کنندگان به استعلام"),
    ]),
    ("FINANCE", "مالی و بدهی", [
        ("BALANCES", "ماندهٔ حساب تامین‌کنندگان"), ("AGING", "سنی‌بندی بدهی‌ها"),
        ("FORECAST", "پیش‌بینی پرداخت‌ها"), ("STATEMENT", "صورت‌حساب تامین‌کننده"),
        ("PREPAYMENTS", "پیش‌پرداخت‌ها و سفارش‌های در جریان"), ("UNPAID", "فاکتورهای پرداخت‌نشده (معوق/سررسیدنشده)"),
        ("PAYMENTS", "پرداخت‌های خرید"), ("COMMITMENTS", "تعهدات خرید و پرداخت"),
        ("VAT", "مالیات بر ارزش افزودهٔ خرید"), ("DPO", "دورهٔ پرداخت بدهی"),
    ]),
    ("INVENTORY", "انبار و تدارکات", [
        ("STOCK_POLICY", "وضعیت موجودی نسبت به سیاست سفارش"), ("SUGGESTED", "پیشنهاد خرید"),
        ("DEMAND_NO_PO", "تقاضای فروش بدون پوشش خرید"), ("REORDER_ANALYSIS", "تحلیل نقطهٔ سفارش و پوشش موجودی"),
        ("SLOW_DEAD", "کالاهای راکد و کم‌گردش"),
    ]),
    ("MASTER", "اطلاعات پایه", [
        ("SUPPLIERS", "فهرست تامین‌کنندگان"), ("ITEMS", "کالاهای قابل‌خرید و واحدها"),
        ("PRICE_LISTS", "فهرست قیمت تامین‌کنندگان"), ("REBATES", "قراردادهای تخفیف حجمی"),
        ("WAREHOUSES", "انبارها و انباردار مسئول"), ("SUPPLIER_TERMS", "شرایط پرداخت و تحویل تامین‌کنندگان"),
        ("CONTRACTS", "قراردادهای خرید"), ("DISCOUNT_RULES", "قواعد تخفیف"), ("RETURN_REASONS", "علت‌های برگشت"),
        ("APPROVAL_RULES", "قواعد تایید و گردش کار"), ("PURCHASE_TYPES", "انواع خرید"),
        ("CANCEL_REASONS", "علت‌های لغو"), ("REORDER_POLICIES", "سیاست‌های سفارش کالا"),
    ]),
]


# R236: منویِ «گزارش‌ها ‹ گزارشاتِ فروش» -- (کد، برچسب) = services/purchase_reports.SALES_REPORTS؛
# dict = صفحه‌هایِ گزارشِ فروشِ قبلی
SALES_REPORT_MENU = [
    ("OPS", "عملیاتی", [
        ("REG_INVOICE", "دفتر فاکتورهای فروش"), ("REG_INVOICE_LINES", "ریز اقلام فاکتورهای فروش"),
        ("REG_ORDER", "دفتر سفارش‌های فروش"), ("REG_PROFORMA", "دفتر پیش‌فاکتورهای فروش"),
        ("OPEN_ORDERS", "سفارش‌های فروش باز"), ("OVERDUE", "سفارش‌های معوق در تحویل"),
        ("PENDING_ISSUES", "حواله‌های در انتظار انبار"), ("DELIVERED_NOT_INVOICED", "تحویل‌شده ولی فاکتورنشده"),
        ("PENDING_INVOICES", "فاکتورهای فروش در انتظار"), ("CONSIGNMENTS", "امانی‌های خروجی تسویه‌نشده"),
        ("RETURNS", "برگشت از فروش"),
    ]),
    ("ANALYSIS", "تحلیل فروش", [
        ("BY_ITEM", "فروش به تفکیک کالا"), ("BY_CUSTOMER", "فروش به تفکیک مشتری"),
        ("BY_CATEGORY", "فروش به تفکیک گروه کالا"), ("BY_COST_CENTER", "فروش به تفکیک مرکز هزینه/پروژه"),
        ("BY_REP", "فروش به تفکیک فروشنده/ویزیتور"), ("MONTHLY", "روند ماهانهٔ فروش"), ("ABC", "تحلیل ABC فروش (پارتو)"),
        {"code": "REPORTS_SALES_BY_ITEM", "label": "گزارش فروش (خلاصهٔ کالا)", "screen": "report_sales"},
        {"code": "REPORTS_SALES_BY_CHANNEL", "label": "گزارش فروش بر اساس کانال", "screen": "report_sales_by_channel"},
        {"code": "REPORTS_SALES_FORECAST", "label": "پیش‌بینی فروش", "screen": "report_sales_forecast"},
    ]),
    ("PROFIT", "سود، قیمت و تخفیف", [
        ("GP_ITEM", "سود ناخالص به تفکیک کالا"), ("GP_CUSTOMER", "سود ناخالص به تفکیک مشتری"),
        {"code": "REPORTS_CUSTOMER_PROFIT", "label": "سود واقعی مشتریان", "screen": "report_customer_profit"},
        ("PRICE_HISTORY", "تاریخچهٔ قیمت فروش"), ("PRICE_COMPARE", "مقایسهٔ قیمت فروش به مشتریان"),
        ("DISCOUNTS", "تخفیف‌های فروش"), ("CORRECTIONS", "اصلاحیه‌های فاکتور فروش"),
    ]),
    ("DELIVERY", "عملکرد تحویل", [
        ("OTD", "تحویل به‌موقع به مشتری"), ("FILL_RATE", "دقت مقدار تحویل به مشتری"),
        ("LEAD_TIME", "زمان تحویل سفارش"), ("QUALITY", "نرخ برگشت از فروش"),
    ]),
    ("FINANCE", "مالی و مطالبات", [
        ("BALANCES", "ماندهٔ حساب مشتریان"), ("AGING", "سنی‌بندی مطالبات"), ("FORECAST", "پیش‌بینی وصول"),
        ("STATEMENT", "صورت‌حساب مشتری"), ("PREPAYMENTS", "پیش‌دریافت‌های مشتریان"),
    ]),
    ("MASTER", "اطلاعات پایه", [
        ("CUSTOMERS", "فهرست مشتریان"), ("ITEMS", "کالاهای قابل‌فروش و واحدها"),
        ("PRICE_LISTS", "فهرست‌های قیمت فروش"), ("WAREHOUSES", "انبارها و انباردار مسئول"),
    ]),
]


# R245: گزارش‌هایِ حسابداری -- صفحه‌هایِ اختصاصیِ قبلی (dict) + موتورِ عمومی (services/accounting_reports.py)
ACCOUNTING_REPORT_MENU = [
    ("LEDGERS", "دفاتر و تراز", [
        {"code": "REPORTS_TRIAL_BALANCE", "label": "تراز آزمایشی", "screen": "report_trial_balance"},
        {"code": "REPORTS_JOURNAL_BOOK", "label": "دفتر روزنامه", "screen": "report_journal_book"},
        {"code": "REPORTS_ACCOUNT_LEDGER", "label": "دفتر کل / معین / تفصیلی", "screen": "report_account_ledger"},
        ("COMPARATIVE_TB", "تراز مقایسه‌ای"),
    ]),
    ("STATEMENTS", "صورت‌های مالی", [
        {"code": "REPORTS_INCOME_STATEMENT", "label": "صورت سود و زیان", "screen": "report_income_statement"},
        {"code": "REPORTS_BALANCE_SHEET", "label": "ترازنامه", "screen": "report_balance_sheet"},
        {"code": "REPORTS_CASH_FLOW", "label": "صورت گردش وجوه نقد", "screen": "report_cash_flow"},
        {"code": "REPORTS_EQUITY_CHANGES", "label": "تغییرات در حقوق صاحبان سهام", "screen": "report_equity_changes"},
        {"code": "REPORTS_CUSTOM_STATEMENT", "label": "گزارش سفارشی (طبق الگو)", "screen": "report_custom_statement"},
        {"code": "REPORTS_STATEMENT_DESIGNER", "label": "طراحی الگوی گزارش", "screen": "statement_template_designer"},
    ]),
    ("FS_ANALYSIS", "تحلیل صورت‌های مالی", [
        {"code": "REPORTS_FINANCIAL_RATIOS", "label": "نسبت‌های مالی", "screen": "report_financial_ratios"},
        {"code": "REPORTS_PERIOD_COMPARISON", "label": "مقایسهٔ دوره‌ای", "screen": "report_period_comparison"},
        ("IS_ANALYSIS", "تحلیل عمودی و افقی سود و زیان"), ("BS_ANALYSIS", "تحلیل عمودی و افقی ترازنامه"),
        {"code": "REPORTS_COST_CENTER", "label": "گزارش مرکز هزینه و پروژه", "screen": "report_cost_center_breakdown"},
    ]),
    ("ACCOUNTS", "تحلیل حساب‌ها", [
        ("ACCOUNT_PERIOD_MATRIX", "گردش دوره‌ای حساب‌ها (ماهانه/فصلی/سالانه)"),
        ("MONTHLY_BALANCE", "گردش و ماندهٔ ماهانهٔ حساب"), ("CONTRA_ACCOUNTS", "تحلیل طرف‌حساب"),
        ("DETAIL_BY_ACCOUNT", "گردش تفصیلی‌ها به تفکیک حساب"), ("ABNORMAL_BALANCES", "حساب‌های با ماندهٔ خلاف ماهیت"),
        ("DORMANT_ACCOUNTS", "حساب‌های راکد"),
    ]),
    ("VOUCHERS", "اسناد و دفاتر", [
        ("VOUCHER_REGISTER", "دفتر ثبت اسناد حسابداری"), ("DAILY_SUMMARY", "خلاصهٔ روزانهٔ اسناد"),
        ("VOUCHERS_BY", "اسناد به تفکیک نوع/وضعیت/کاربر/منبع/ماه"), ("SPECIAL_ENTRIES", "اسناد افتتاحیه، اختتامیه و تعدیلی"),
        ("REVERSED_ENTRIES", "اسناد برگشتی و باطل‌شده"),
    ]),
    ("AUDIT", "کنترل و حسابرسی اسناد", [
        {"code": "REPORTS_ANOMALIES", "label": "تشخیص سندهای ناقص یا غیرعادی", "screen": "report_anomalies"},
        ("UNBALANCED", "اسناد نامتوازن"), ("NUMBER_GAPS", "شکاف و تکرار در شماره‌گذاری اسناد"),
        ("UNPOSTED", "اسناد پیش‌نویس و موقت قطعی‌نشده"), ("BACKDATED", "اسناد عطف به ماسبق / تاریخ آینده"),
        ("OFF_HOURS", "اسناد ثبت‌شده در تعطیلی یا خارج از ساعت کاری"), ("LARGE_LINES", "بزرگ‌ترین ردیف‌های اسناد"),
        ("ROUND_AMOUNTS", "ردیف‌های با مبلغ رُند"), ("SELF_APPROVED", "اسناد تاییدشده توسط صادرکننده (تفکیک وظایف)"),
    ]),
]


# R246: منویِ «گزارش‌ها ‹ انبار» -- (کد، برچسب) = services/warehouse_reports.WAREHOUSE_REPORTS
WAREHOUSE_REPORT_MENU = [
    ("DASH", "داشبورد", [
        {"code": "INV_RPT_DASHBOARD", "label": "داشبورد انبار", "screen": "warehouse_dashboard"},
    ]),
    # R259: بهایِ تمام‌شده و ارزش‌گذاریِ موجودی
    ("COSTING", "بهای تمام‌شده", [
        ("COST_VALUATION", "ارزش‌گذاری موجودی"), ("COST_LAYERS", "لایه‌های هزینه"), ("COST_ALLOCATION", "تخصیص بهای خروج"),
        ("COST_HISTORY", "تاریخچهٔ بهای کالا"), ("COST_COGS", "بهای تمام‌شدهٔ فروش و سود ناخالص"),
        ("COST_REPLACEMENT", "بهای جایگزینی"), ("COST_VARIANCE", "مغایرت بها"), ("COST_PENDING", "بهای در انتظار"),
        ("COST_CENTER", "بهای مصرف به تفکیک مرکز هزینه/پروژه"),
    ]),
    ("STOCK", "موجودی", [
        ("STOCK_ON_HAND", "موجودی لحظه‌ای"), ("STOCK_BY_WAREHOUSE", "موجودی به تفکیک انبار"),
        ("STOCK_BY_CATEGORY", "موجودی به تفکیک گروه کالا"), ("STOCK_BY_BRAND", "موجودی به تفکیک برند"),
        ("ZERO_STOCK", "کالاهای بدون موجودی"), ("NEGATIVE_STOCK", "موجودی منفی"), ("RESERVED_STOCK", "موجودی رزروشده"),
        ("FREE_STOCK", "موجودی آزاد"), ("QUARANTINE_STOCK", "موجودی قرنطینه و مسدود"), ("CONSIGNMENT_STOCK", "موجودی امانی"),
    ]),
    ("CARD", "کاردکس و گردش", [
        ("STOCK_CARD", "کاردکس کالا"),
        {"code": "REPORTS_ITEM_LEDGER", "label": "کاردکس کالا (نمای قبلی)", "screen": "report_item_ledger"},
        ("ITEM_MOVEMENT", "گردش کالا (روزانه/هفتگی/ماهانه/سالانه)"), ("MOVEMENT_BY_TYPE", "گردش به تفکیک نوع"),
    ]),
    ("VALUE", "ارزش موجودی", [
        ("VALUATION", "ارزش موجودی"), ("VALUE_TREND", "روند ارزش موجودی"),
    ]),
    ("ANALYSIS", "تحلیل موجودی", [
        ("STOCK_AGING", "سن موجودی"), ("SLOW_MOVING", "کالاهای کم‌گردش"), ("DEAD_STOCK", "کالاهای راکد"),
        ("OVERSTOCK", "کالاهای مازاد"), ("STOCK_COVERAGE", "پوشش موجودی (روز)"),
        ("REORDER", "کالاهای رسیده به نقطهٔ سفارش"), ("ABC", "تحلیل ABC موجودی"), ("ABC_XYZ", "ماتریس ABC–XYZ"),
    ]),
    ("COUNT", "شمارش و مغایرت", [
        ("VARIANCE", "مغایرت موجودی"), ("STOCK_COUNTS", "گزارش انبارگردانی‌ها"), ("COUNTER_PERFORMANCE", "عملکرد شمارشگران"),
        ("CYCLE_COUNT", "شمارش دوره‌ای"), ("CYCLE_COUNT_DUE", "شمارش‌های سررسیدشده"),
        ("ACCURACY", "دقت موجودی"),
    ]),
    ("LOTS", "بچ، انقضا و سریال", [
        ("BATCH_STOCK", "موجودی بچ/لات"), ("EXPIRY", "انقضای کالا"), ("SERIALS", "شماره‌سریال‌ها"),
    ]),
    ("OPS", "عملیات انبار", [
        ("RECEIVING", "رسیدها"), ("ISSUES", "حواله‌ها"), ("TRANSFERS", "انتقال‌های بین انبار"),
        ("REPLENISHMENT", "پیشنهاد تامین مجدد"), ("PRODUCTIVITY", "بهره‌وری انبار"), ("CAPACITY", "ظرفیت انبار"),
        ("BIN_STOCK", "موجودی به تفکیک محل نگهداری"),
    ]),
    ("WMS", "جانمایی و برداشت", [
        ("PUTAWAY", "جانمایی"), ("UNLOCATED_STOCK", "دریافت‌شده ولی جانمایی‌نشده"), ("PICKING", "برداشت"),
        ("WMS_PERFORMANCE", "عملکرد اپراتورهای انبار"),
        # R252: گزارش‌هایِ محل‌محور
        ("BIN_BATCH_STOCK", "بچ به تفکیک محل"), ("WAVES", "موج‌های برداشت"), ("LOCATION_COUNTS", "شمارش‌های محل"),
        ("REPLENISH_TASKS", "تامین مجدد محل‌های برداشت"),
    ]),
    ("MASTER", "اطلاعات پایه", [
        ("MD_WAREHOUSES", "فهرست انبارها"), ("MD_UNITS", "واحدها و تبدیل واحد کالاها"),
        ("MD_TRACKED", "کالاهای دارای سریال/بچ/انقضا"), ("MD_MIN_MAX", "کالاهای دارای حداقل/حداکثر موجودی"),
    ]),
]

# R264: «گزارش‌ها ‹ دارایی‌هایِ ثابت» -- (کد، برچسب) = services/fixed_assets/reports.FA_REPORTS (همان موتور/صفحهٔ گزارش)
FA_REPORT_MENU = [
    ("FA", "دارایی‌های ثابت", [
        ("FA_REGISTER", "دفتر دارایی‌های ثابت"), ("FA_DEPRECIATION", "گزارش استهلاک"), ("FA_MOVEMENT", "گردش دارایی‌ها"),
        ("FA_FULLY_DEPRECIATED", "دارایی‌های کاملاً مستهلک"), ("FA_BY_LOCATION", "به تفکیک محل"),
        ("FA_BY_BRANCH", "به تفکیک شعبه"), ("FA_BY_COST_CENTER", "به تفکیک مرکز هزینه"), ("FA_BY_CATEGORY", "به تفکیک طبقه"),
        ("FA_CIP", "دارایی‌های در جریان تکمیل"), ("FA_DISPOSALS", "واگذاری‌ها"), ("FA_GAIN_LOSS", "سود و زیان واگذاری"),
        ("FA_PHYSICAL", "شمارش فیزیکی"), ("FA_AGING", "سن دارایی‌ها"), ("FA_FORECAST", "پیش‌بینی استهلاک"),
        ("FA_MACHINE_COST", "بهای ماشین‌آلات تولید"),
    ]),
]

# R270: «گزارش‌ها ‹ تولید» -- services/production/reports.PRODUCTION_REPORTS
PRD_REPORT_MENU = [
    ("PRD", "تولید", [
        ("PRD_ORDERS", "دستورهای تولید"), ("PRD_BY_PRODUCT", "تولید به تفکیک محصول"), ("PRD_BY_WAREHOUSE", "تولید به تفکیک انبار"),
        ("PRD_BY_BRANCH", "تولید به تفکیک شعبه"), ("PRD_BY_PERIOD", "تولید به تفکیک دوره"),
        ("PRD_BY_WORK_CENTER", "تولید به تفکیک مرکز کاری"),
    ]),
    ("PRD_MAT", "مواد", [
        ("PRD_MATERIAL_CONSUMPTION", "مصرف مواد"), ("PRD_MATERIAL_VARIANCE", "انحراف مواد"),
        ("PRD_MATERIAL_WASTE", "ضایعات و هدررفت مواد"), ("PRD_MATERIAL_REQUIREMENT", "نیاز مواد"),
    ]),
    ("PRD_COST", "بهای تمام‌شده", [
        ("PRD_COST", "بهای تمام‌شدهٔ تولید"), ("PRD_UNIT_COST", "بهای واحد محصول"), ("PRD_STD_VS_ACTUAL", "استاندارد در برابر واقعی"),
        ("PRD_COST_VARIANCE", "تحلیل انحراف بها"), ("PRD_OVERHEAD", "تخصیص سربار"), ("PRD_LABOR", "هزینهٔ دستمزد"),
        ("PRD_MACHINE", "هزینهٔ ماشین"),
    ]),
    ("PRD_INV", "موجودی تولید", [
        ("PRD_WIP", "کالای در جریان ساخت (WIP)"), ("PRD_SEMI_STOCK", "موجودی نیمه‌ساخته"), ("PRD_FG_STOCK", "موجودی محصول نهایی"),
        ("PRD_SCRAP", "ضایعات"), ("PRD_BYPRODUCTS", "محصولات جانبی و مشترک"),
    ]),
    ("PRD_MGMT", "مدیریتی", [
        ("PRD_PROFITABILITY", "سودآوری تولید"), ("PRD_COST_TREND", "روند بهای تمام‌شده"), ("PRD_EFFICIENCY", "کارایی تولید"),
        ("PRD_CAPACITY", "بهره‌برداری از ظرفیت"), ("PRD_SCRAP_ANALYSIS", "تحلیل ضایعات"), ("PRD_TRACE", "ردیابی تولید"),
    ]),
]


def _report_menu(prefix: str, screen_prefix: str, menu: list) -> list[dict]:
    return [
        {
            "code": f"{prefix}_GRP_{group_code}",
            "label": group_label,
            "children": [
                entry if isinstance(entry, dict)
                else {"code": f"{prefix}_{entry[0]}", "label": entry[1], "screen": f"{screen_prefix}{entry[0].lower()}"}
                for entry in entries
            ],
        }
        for group_code, group_label, entries in menu
    ]


NAV_ITEMS = [
    {"code": "dashboard", "label": "داشبورد", "screen": "dashboard"},
    # طبقِ درخواستِ صریح («سیستمِ کارتابل قابلِ‌گسترش برایِ همه‌یِ ماژول‌ها»):
    # این آیتم عمداً بالایِ ساید‌بار و مستقلِ از هر ماژول است — کارتابل هر
    # کاربر می‌تواند هم‌زمان اقلامی از حسابداری/خزانه‌داری/هر ماژولِ دیگر
    # داشته باشد، پس زیرِ هیچ‌کدام قرار نمی‌گیرد (services/cartable.py).
    {"code": "MY_TASKS", "label": "کارتابل من", "screen": "my_tasks"},
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
            {"code": "GL_DIM_CONFIG", "label": "پیکربندی گروه‌های تفصیلی", "screen": "dimension_group_config", "in_ribbon": False},
            {"code": "GL_DIM", "label": "تعریف تفصیلی", "screen": "detail_dimensions", "in_ribbon": False},
        ],
    },
    {
        "code": "TREASURY",
        "label": "خزانه‌داری",
        "children": [
            # طبقِ طرحِ تاییدشده (فازِ ۲): فرمِ دریافت/پرداخت حالا چندروشی
            # است (نقد/بانک/چک/تخفیف در یک سند) — هر ردیف طبقِ نگاشتِ
            # حساب‌هایِ تنظیماتِ خزانه‌داری خودکار به حسابِ کلِ خودش می‌رود.
            {"code": "TREASURY_RECEIPT", "label": "سند دریافت", "screen": "treasury_voucher_receipt"},
            {"code": "TREASURY_PAYMENT", "label": "سند پرداخت", "screen": "treasury_voucher_payment"},
            {"code": "TREASURY_LIST", "label": "اسناد خزانه‌داری", "screen": "treasury_vouchers_list"},
            # طبقِ درخواستِ صریح («هر دریافت و پرداخت رفرنسِ فاکتور را
            # داشته باشد و مدیریتِ تسویه‌یِ فاکتورها را ایجاد کن»): تخصیصِ
            # (بخشی از) یک سندِ دریافت/پرداختِ ثبت‌شده به یک یا چند فاکتورِ
            # بازِ فروش/خرید.
            # طبقِ درخواستِ صریح («فرمِ تسویه‌یِ فاکتورهایِ خرید و فروش جدا از
            # هم باشه»): یک آیتمِ مشترک قبلاً هردو را با هم نشان می‌داد.
            {"code": "TREASURY_SETTLEMENT_SALES", "label": "تسویهٔ فاکتورهای فروش", "screen": "commercial_invoice_settlement_sales"},
            {"code": "TREASURY_SETTLEMENT_PURCHASE", "label": "تسویهٔ فاکتورهای خرید", "screen": "commercial_invoice_settlement_purchase"},
            # طبقِ درخواستِ صریح («روشِ دریافت/پرداختِ اقساطی»): دیدِ کلیِ
            # همه‌یِ اقساطِ برنامه‌ریزی‌شده -- خودِ دریافت/پرداخت از فرمِ
            # بالا (دکمه‌یِ 🔗) انجام می‌شود.
            {"code": "TREASURY_INSTALLMENTS", "label": "مدیریت اقساط", "screen": "installments_list"},
            # طبقِ ساختارِ واقعیِ تنخواه‌گردان: هر تنخواه‌دار (تفصیلیِ سطحِ
            # آخرِ گروهِ «تنخواه») چند تنخواهِ باز با شماره‌یِ خودکارِ
            # مستقل می‌تواند داشته باشد.
            {"code": "TREASURY_PETTY_CASH", "label": "تنخواه‌گردان", "screen": "treasury_petty_cash"},
            {"code": "TREASURY_PETTY_CASH_LIST", "label": "اسناد تنخواه‌گردان", "screen": "treasury_petty_cash_list"},
            {"code": "TREASURY_CHECKS_RECEIVED", "label": "چک‌های دریافتی", "screen": "treasury_checks_received"},
            {"code": "TREASURY_CHECKS_ISSUED", "label": "چک‌های پرداختی", "screen": "treasury_checks_issued"},
            {"code": "TREASURY_CHECKS_DUE", "label": "گزارش چک‌های درجریان وصول", "screen": "treasury_checks_due"},
            # طبقِ درخواستِ صریح: گزارشِ عمومیِ چک‌ها (نه فقط درجریانِ وصول) —
            # فیلترِ نوع/سررسید/تاریخِ دریافت‌وصدور/طرفِ‌حساب/وضعیت/بانک + چاپ.
            {"code": "TREASURY_CHECKS_REPORT", "label": "گزارش چک‌ها", "screen": "report_checks"},
            # طبقِ آیتمِ ۵ («مغایرتِ بانکی/حساب از اکسل، فقط نمایشِ
            # اختلاف‌ها»): مقایسه‌یِ صورت‌حسابِ اکسلِ بانک با گردشِ همان
            # حساب در دفتر — بدونِ مکانیزمِ تطبیق‌دادنِ دستی.
            {"code": "TREASURY_RECONCILIATION", "label": "مغایرت بانکی/حساب", "screen": "bank_reconciliation"},
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
            {"code": "INV_DOCUMENTS_LIST", "label": "اسناد انبار", "screen": "inventory_documents_list"},
            {"code": "INV_RECEIPT", "label": "رسید", "screen": "inventory_document_receipt"},
            {"code": "INV_ISSUE", "label": "حواله", "screen": "inventory_document_issue"},
            {"code": "INV_TRANSFER", "label": "انتقال", "screen": "inventory_document_transfer"},
            # طبقِ تشخیصِ صریح («سندِ برگشت از فروش/به تامین‌کننده چه فرقی
            # با نسخه‌یِ انبار دارد؟»): این دو کد صرفاً برایِ حلِ کدیِ
            # مسیرِ «مشاهده/ویرایشِ» یک سندِ RETURN_IN/RETURN_OUت که خودِ
            # سندِ تجاریِ SALES_RETURN/PURCHASE_RETURN بعدِ ثبتِ‌نهایی
            # به‌صورتِ خودکار می‌سازد (نگاه کن: inventory_documents_list.py،
            # commercial_documents.py::_STOCK_DOCUMENT_TYPE_BY_COMMERCIAL)
            # زنده نگه داشته می‌شوند -- دیگر در ساید‌بار نمایش داده
            # نمی‌شوند (hidden_from_sidebar) چون ساختنِ دستیِ این سند از
            # این مسیر، مسیرِ صحیح و کاملِ تجاری (قیمت/مالیات/تسویه) را
            # دور می‌زند و ریسکِ ثبتِ دوباره/نادرستِ حسابداری دارد.
            {"code": "INV_RETURN_IN", "label": "برگشت از فروش", "screen": "inventory_document_return_in", "hidden_from_sidebar": True},
            {"code": "INV_RETURN_OUT", "label": "برگشت به تامین‌کننده", "screen": "inventory_document_return_out", "hidden_from_sidebar": True},
            {"code": "INV_ADJUSTMENT", "label": "اصلاح موجودی", "screen": "inventory_document_adjustment"},
            # سیستمِ واحد (R225): شمارشِ موجودی با واحدِ دلخواه (کارتن/بسته/عدد)؛
            # اختلاف به واحدِ پایه با سندِ اصلاحِ موجودی ثبت می‌شود.
            {"code": "INV_STOCK_COUNT", "label": "انبارگردانی", "screen": "stock_count"},
            # R247: وظایفِ جانمایی/برداشت و برنامهٔ شمارشِ دوره‌ای
            {"code": "INV_WMS_TASKS", "label": "جانمایی، برداشت و برنامهٔ شمارش", "screen": "warehouse_operations"},
            # R248: نقشهٔ تعاملی و مدیریتِ محل‌هایِ انبار (Zone/Aisle/Rack/Level/Bin)
            {"code": "INV_WAREHOUSE_MAP", "label": "نقشه و محل‌های انبار", "screen": "warehouse_map"},
            {"code": "INV_LOT_TRACE", "label": "ردیابی بچ/سریال/امانی", "screen": "lot_trace"},
            {"code": "INV_RESIDUAL_ADJUST", "label": "تسعیر/اصلاح ماندهٔ ریالی موجودی", "screen": "inventory_residual"},
            # طبقِ درخواستِ صریح («فاکتورِ امانی -- هردو جهت»): دیدِ کلیِ
            # مانده‌یِ همه‌یِ اسنادِ امانیِ بازِ خروجی/ورودی + بازگردانیِ
            # کالایِ فروخته‌نشده/مصرف‌نشده (تسویه‌یِ واقعی از طریقِ همان
            # دکمه‌یِ «تبدیل به فاکتور» در خودِ فرمِ سند انجام می‌شود).
            {"code": "INV_CONSIGNMENT_TRACKING", "label": "پیگیری امانی", "screen": "commercial_consignment_tracking"},
        ],
    },
    # R272: آیتم‌هایِ تنظیماتِ COSTING/FA/PRD فقط برایِ دسترسی می‌مانند و در منو دیده نمی‌شوند؛
    # تنظیمات در «تنظیماتِ سیستم» است و چرخ‌دندهٔ کنارِ گروه مستقیم به آن می‌رود.
    # R261: بهایِ تمام‌شده ماژولِ مستقلِ منویِ اصلی است (گزارش‌ها همان صفحهٔ عمومیِ گزارشِ انبار)
    {
        "code": "COSTING",
        "label": "بهای تمام‌شده",
        "children": [
            {"code": "COST_DASHBOARD", "label": "داشبورد بهای تمام‌شده", "screen": "costing_dashboard"},
            {"code": "COST_SETTINGS", "label": "تنظیمات بهای تمام‌شده", "screen": "costing_settings", "hidden_from_sidebar": True},
            {"code": "COST_LAYERS", "label": "لایه‌های هزینه", "screen": "warehouse_report_cost_layers"},
            {"code": "COST_HISTORY", "label": "تاریخچهٔ بها", "screen": "warehouse_report_cost_history"},
            {"code": "COST_VALUATION", "label": "ارزش‌گذاری موجودی", "screen": "warehouse_report_cost_valuation"},
            {"code": "COST_ALLOCATION", "label": "تخصیص بهای خروج", "screen": "warehouse_report_cost_allocation"},
            {"code": "COST_COGS", "label": "بهای تمام‌شدهٔ فروش", "screen": "warehouse_report_cost_cogs"},
            {"code": "COST_REPLACEMENT", "label": "بهای جایگزینی", "screen": "costing_replacement"},
            {"code": "COST_RECALC", "label": "بازمحاسبهٔ بها", "screen": "costing_recalculation"},
            {"code": "COST_CENTER", "label": "هزینه‌یابی مرکز هزینه/پروژه", "screen": "warehouse_report_cost_center"},
        ],
    },
    # R265: دارایی‌هایِ ثابت -- ماژولِ مستقل؛ صفحهٔ «دارایی‌ها» مرکزِ عملیات است
    {
        "code": "FA",
        "label": "دارایی‌های ثابت",
        "children": [
            {"code": "FA_DASHBOARD", "label": "داشبورد دارایی‌ها", "screen": "fa_dashboard"},
            {"code": "FA_ASSETS", "label": "دارایی‌ها", "screen": "fa_assets"},
            {"code": "FA_DEPRECIATION", "label": "اجرای استهلاک", "screen": "fa_depreciation"},
            {"code": "FA_CIP", "label": "دارایی در جریان تکمیل", "screen": "fa_cip"},
            {"code": "FA_PHYSICAL", "label": "شمارش فیزیکی", "screen": "fa_physical_count"},
            {"code": "FA_SETUP", "label": "تنظیمات و طبقه‌ها", "screen": "fa_setup", "hidden_from_sidebar": True},
            {"code": "FA_REPORTS", "label": "گزارش‌ها", "children": [
                {"code": "FA_RPT_REGISTER", "label": "دفتر دارایی‌ها", "screen": "warehouse_report_fa_register"},
                {"code": "FA_RPT_DEPRECIATION", "label": "گزارش استهلاک", "screen": "warehouse_report_fa_depreciation"},
                {"code": "FA_RPT_MOVEMENT", "label": "گردش دارایی‌ها", "screen": "warehouse_report_fa_movement"},
                {"code": "FA_RPT_DISPOSALS", "label": "واگذاری‌ها و سود/زیان", "screen": "warehouse_report_fa_disposals"},
                {"code": "FA_RPT_FORECAST", "label": "پیش‌بینی استهلاک", "screen": "warehouse_report_fa_forecast"},
                {"code": "FA_RPT_MACHINE", "label": "بهای ماشین‌آلات تولید", "screen": "warehouse_report_fa_machine_cost"},
            ]},
        ],
    },
    # R270: تولید -- «دستورهایِ تولید» صفحهٔ مرکزی است؛ اطلاعاتِ پایه/برنامه‌ریزی/بها پشتِ آن
    {
        "code": "PRD",
        "label": "تولید",
        "children": [
            {"code": "PRD_DASHBOARD", "label": "داشبورد تولید", "screen": "prd_dashboard"},
            {"code": "PRD_ORDERS", "label": "دستورهای تولید", "screen": "prd_orders"},
            {"code": "PRD_PLANNING", "label": "برنامه‌ریزی، نیاز مواد و ظرفیت", "screen": "prd_planning"},
            {"code": "PRD_MASTER", "label": "اطلاعات پایه (فهرست مواد، مسیر، مرکز کاری)", "screen": "prd_master"},
            {"code": "PRD_COSTING", "label": "بهای تمام‌شده، سربار و بستن دوره", "screen": "prd_costing"},
            {"code": "PRD_SETTINGS", "label": "تنظیمات تولید", "screen": "prd_settings", "hidden_from_sidebar": True},
            {"code": "PRD_REPORTS", "label": "گزارش‌ها", "children": [
                {"code": "PRD_RPT_ORDERS", "label": "دستورهای تولید", "screen": "warehouse_report_prd_orders"},
                {"code": "PRD_RPT_COST", "label": "بهای تمام‌شدهٔ تولید", "screen": "warehouse_report_prd_cost"},
                {"code": "PRD_RPT_VARIANCE", "label": "تحلیل انحراف بها", "screen": "warehouse_report_prd_cost_variance"},
                {"code": "PRD_RPT_WIP", "label": "کالای در جریان ساخت", "screen": "warehouse_report_prd_wip"},
                {"code": "PRD_RPT_PROFIT", "label": "سودآوری تولید", "screen": "warehouse_report_prd_profitability"},
                {"code": "PRD_RPT_TRACE", "label": "ردیابی تولید", "screen": "warehouse_report_prd_trace"},
            ]},
        ],
    },
    {
        "code": "SALES",
        "label": "فروش و بازاریابی",
        "children": [
            # طبقِ درخواستِ صریح («دستیارِ فروش داخلِ ERP»): فهرستِ رتبه‌بندی‌
            # شده‌یِ مهم‌ترین اقداماتِ امروز (ریسکِ ریزش/فروشِ مکمل/رشدِ مشتری).
            {"code": "SALES_ASSISTANT", "label": "دستیار فروش", "screen": "sales_assistant"},
            {"code": "SALES_ORDER", "label": "سفارش فروش", "screen": "commercial_document_sales_order"},
            {"code": "SALES_PROFORMA", "label": "پیش‌فاکتور فروش", "screen": "commercial_document_sales_proforma"},
            {"code": "SALES_INVOICE", "label": "فاکتور فروش", "screen": "commercial_document_sales_invoice"},
            {"code": "SALES_RETURN", "label": "برگشت از فروش", "screen": "commercial_document_sales_return"},
            # طبقِ درخواستِ صریح («فاکتورِ امانی -- هردو جهت»): امانیِ
            # خروجی از نظرِ طرفِ‌حساب هم‌الگویِ فروش است.
            {"code": "SALES_CONSIGNMENT_OUT", "label": "امانی خروجی", "screen": "commercial_document_consignment_out"},
            # R232: همان فرمِ تاییدِ انبار (رسید/حواله) -- حوالهٔ سفارش‌هایِ فروش برایِ انباردار
            {"code": "SALES_WAREHOUSE_ISSUE", "label": "تایید حوالهٔ انبار", "screen": "purchase_goods_receipt"},
            {"code": "SALES_DOCUMENTS_LIST", "label": "اسناد فروش", "screen": "commercial_documents_list_sales"},
            {"code": "SALES_PRICING", "label": "فهرست قیمت و تخفیف", "screen": "commercial_pricing"},
            {"code": "SALES_POS_SALE", "label": "فروش حضوری (POS)", "screen": "commercial_pos_sale"},
            {"code": "SALES_POS_APPROVAL", "label": "تایید سرپرست — فروش حضوری", "screen": "commercial_pos_approval"},
            # طبقِ بازخوردِ صریحِ کاربر («منویِ اصلی شلوغ شده، فقط فروشِ
            # اینترنتی باید آنجا باشد»): سفارش‌ها + تقویمِ محتوا/پستِ
            # خودکار + سینکِ CMS + مرکزِ رسانه + نگهبانِ اتصال، همگی زیرِ
            # همین یک آیتم، در یک فرمِ تب‌دار (commercial_online_sales_hub)
            # -- نه پنج آیتمِ جداگانه در منویِ اصلی. اتصالات/نگاشت/
            # مسیریابیِ کلی همچنان در تبِ «تنظیماتِ فروشِ اینترنتی» زیرِ
            # «تنظیمات سیستم ‹ مدیریتِ بازرگانی» می‌ماند.
            {"code": "SALES_ECOMMERCE", "label": "فروش اینترنتی", "screen": "commercial_online_sales_hub"},
            # طبقِ درخواستِ صریحِ بعدیِ کاربر («قسمتِ پخشِ سرد جدا باید
            # باشه، فرمِ جدا براش درست کن»): روالِ کاملِ پخشِ سرد (سفارش ->
            # تاییدِ انبار/توزین -> تبدیل به فاکتور -> تیمِ پخش) دیگر تبی
            # زیرِ «پخشِ کالا» نیست -- آیتمِ ناوبریِ مستقلِ خودش را دارد.
            {"code": "SALES_COLD_DISTRIBUTION", "label": "پخش سرد (سفارش‌گیری)", "screen": "cold_distribution"},
            # طبقِ درخواستِ صریحِ کاربر («وقتی منویِ پخشِ گرم اجرا می‌شود
            # فقط تب‌هایِ مربوط به پخشِ گرم باز شود و بقیهٔ تب‌ها در
            # منویِ مربوط به خودشون ایجاد بشه»): دیگر «ابزارهایِ میدانیِ
            # مشترک» زیرِ همین آیتم نیست -- فقط چهار تبِ واقعاً مخصوصِ
            # خودرو/فروشِ خودرویی.
            {"code": "SALES_DISTRIBUTION", "label": "پخش گرم (فروش خودرویی)", "screen": "commercial_distribution_hub"},
            # فروشِ تلفنی: طبقِ همان تفکیک، مخصوصِ سفارش‌گیریِ پخشِ سرد
            # است، نه پخشِ گرم -- آیتمِ ناوبریِ مستقلِ خودش را گرفت.
            {"code": "SALES_TELESALES", "label": "فروش تلفنی", "screen": "commercial_telesales"},
            # برنامهٔ مراجعه/ویزیت‌ها/پروموشن‌ها/داشبوردِ سرپرست/بازاریابی:
            # هیچ‌کدام مخصوصِ پخشِ گرم یا سرد نیستند (هر دو کانال از
            # همین‌ها استفاده می‌کنند) -- طبقِ درخواستِ صریحِ کاربر، فعلاً
            # همه زیرِ یک آیتمِ تب‌دارِ تازه.
            {"code": "SALES_PLANNING", "label": "برنامه‌ریزی فروش", "screen": "sales_planning_hub"},
            {"code": "SALES_AFTERSALES", "label": "خدمات پس‌ازفروش و گارانتی", "screen": "commercial_aftersales"},
        ],
    },
    # R281: مدیریت ارتباط با مشتری — لایه‌ای روی همان مشتری/فروش/دریافت ERP (docs/crm-implementation-plan.md)
    {
        "code": "CRM",
        "label": "مدیریت ارتباط با مشتری",
        "children": [
            {"code": "CRM_CUSTOMER360", "label": "پروندهٔ ۳۶۰ مشتری", "screen": "crm_customer360"},
            {"code": "CRM_TASKS", "label": "مرکز کارها و پیگیری‌ها", "screen": "crm_tasks"},
            {"code": "CRM_LEADS", "label": "سرنخ‌ها", "screen": "crm_leads"},
            {"code": "CRM_PIPELINE", "label": "قیف فروش و فرصت‌ها", "screen": "crm_pipeline"},
            {"code": "CRM_SETTINGS", "label": "تنظیمات ارتباط با مشتری (قیف فروش، منابع سرنخ)", "screen": "crm_settings", "in_ribbon": False},
        ],
    },
    {
        "code": "PURCH",
        "label": "خرید و تدارکات",
        "children": [
            # R241: درخواستِ خرید (پیش از سفارش)
            {"code": "PURCH_REQUESTS", "label": "درخواست خرید", "screen": "purchase_requests"},
            # R242: استعلامِ قیمت و مقایسهٔ پیشنهادها
            {"code": "PURCH_RFQ", "label": "استعلام قیمت", "screen": "rfqs"},
            {"code": "PURCH_ORDER", "label": "سفارش خرید", "screen": "commercial_document_purchase_order"},
            {"code": "PURCH_PROFORMA", "label": "پیش‌فاکتور خرید", "screen": "commercial_document_purchase_proforma"},
            {"code": "PURCH_INVOICE", "label": "فاکتور خرید", "screen": "commercial_document_purchase_invoice"},
            {"code": "PURCH_RETURN", "label": "برگشت به تامین‌کننده", "screen": "commercial_document_purchase_return"},
            # طبقِ درخواستِ صریح («فاکتورِ امانی -- هردو جهت»): امانیِ
            # ورودی از نظرِ طرفِ‌حساب هم‌الگویِ خرید است.
            {"code": "PURCH_CONSIGNMENT_IN", "label": "امانی ورودی", "screen": "commercial_document_consignment_in"},
            {"code": "PURCH_DOCUMENTS_LIST", "label": "اسناد خرید", "screen": "commercial_documents_list_purchase"},
            {"code": "PURCH_EXTRAS", "label": "تخفیف حجمی تامین‌کننده", "screen": "commercial_purchasing_extras"},
            # طبقِ درخواستِ صریح («زیرماژولِ مدیریتِ سفارشات»): پیگیریِ
            # پرداخت‌هایِ سفارشاتِ در راه (ترخیص/بهایِ اولیهٔ کالا و...) با
            # همان فرمِ دریافت/پرداختِ خزانه‌داری.
            {"code": "PURCH_ORDER_TRACKING", "label": "مدیریت سفارشات", "screen": "order_tracking"},
            # طبقِ گزارشِ صریحِ کاربر («بعدِ تاییدِ سفارش، انباردار کجا
            # رسیدِ کالا را تایید کند، بدونِ دیدنِ قیمت؟»): آیتمِ مستقل،
            # نه تبی درونِ فرمِ سفارشِ خرید -- تا بشود فقط همین دسترسی
            # (بدونِ دسترسی به فرمِ کاملِ دارایِ قیمت) به انباردار داد.
            {"code": "PURCH_GOODS_RECEIPT", "label": "تایید رسید کالا", "screen": "purchase_goods_receipt"},
            # R240: انواعِ خرید، علت‌هایِ لغو، سیاستِ سفارشِ کالا
            {"code": "PURCH_MASTERS", "label": "اطلاعات پایهٔ تدارکات", "screen": "procurement_masters"},
        ],
    },
    {
        "code": "HR",
        "label": "منابع انسانی",
        "children": [
            {"code": "HR_ORG_UNITS", "label": "واحدهای سازمانی", "screen": "hr_org_units"},
            {"code": "HR_JOB_GRADES", "label": "رده‌های شغلی", "screen": "hr_job_grades"},
            {"code": "HR_POSITIONS", "label": "پست‌های سازمانی", "screen": "hr_positions"},
            {"code": "HR_PAYROLL_RUN", "label": "اجرای محاسبهٔ حقوق", "screen": "payroll_run"},
            {"code": "HR_PAYROLL_LOANS", "label": "وام و مساعده", "screen": "payroll_loans"},
            # طبقِ یکپارچه‌سازیِ «تعریفِ کارمند فقط از طریقِ تفصیلی»: آیتمِ
            # مستقلِ HR_EMPLOYEES حذف شد (فرمِ تعریفِ کارمند دیگر detail_dimensions
            # است)؛ به‌جایش، ثبت/تاییدِ ساعاتِ اضافه‌کاری این‌جا اضافه شده.
            {"code": "HR_PAYROLL_OVERTIME", "label": "اضافه‌کاری", "screen": "payroll_overtime_entries"},
            # طبقِ گزارشِ صریح («فرمِ ورود و خروجِ کارمندان و فرمِ خلاصهٔ کارکرد
            # نداره»): حضوروغیابِ واقعیِ روزانه، مستقل از ثبتِ ساعاتِ اضافه‌کاری.
            {"code": "HR_ATTENDANCE_ENTRIES", "label": "ورود و خروج کارکنان", "screen": "hr_attendance_entries"},
            {"code": "HR_ATTENDANCE_SUMMARY", "label": "خلاصهٔ کارکرد", "screen": "hr_attendance_summary"},
            # طبقِ درخواستِ صریح: تنظیماتِ حقوق‌ودستمزد از یک آیتمِ مستقل به
            # تبی درونِ «تنظیماتِ سیستم» منتقل شد (هم‌الگو با نگاشتِ
            # صورت‌هایِ مالی) — دسترسی از طریقِ آیکونِ چرخ‌دنده‌یِ همین گروه
            # (_SETTINGS_TAB_BY_GROUP_CODE در shell_window.py).
        ],
    },
    # R245: آیتمِ «فاکتورها» (بدونِ صفحه) حذف شد -- فاکتورها در منوهایِ فروش و خرید هستند.
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
            # R245: گزارش‌هایِ حسابداری در زیرگروه‌هایِ جمع‌شونده (کدهایِ قبلی بدونِ تغییر)
            {"code": "REPORTS_GL", "label": "حسابداری", "children": _report_menu("ACC_RPT", "accounting_report_", ACCOUNTING_REPORT_MENU)},
            # R246: گزارش‌ها و تحلیلِ انبار (services/warehouse_reports.py) -- کاردکسِ قبلی با همان کد
            {"code": "REPORTS_INV", "label": "انبار", "children": _report_menu("INV_RPT", "warehouse_report_", WAREHOUSE_REPORT_MENU)},
            {"code": "REPORTS_FA", "label": "دارایی‌های ثابت", "children": _report_menu("INV_RPT", "warehouse_report_", FA_REPORT_MENU)},
            {"code": "REPORTS_PRD", "label": "تولید", "children": _report_menu("INV_RPT", "warehouse_report_", PRD_REPORT_MENU)},
            # R236: گزارشاتِ خرید و فروش (services/purchase_reports.py، صفحهٔ عمومیِ purchase_reports.py)
            {"code": "REPORTS_PURCHASE", "label": "گزارشات خرید", "children": _report_menu("PURCH_RPT", "purchase_report_", PURCHASE_REPORT_MENU)},
            {"code": "REPORTS_SALES", "label": "گزارشات فروش", "children": _report_menu("SALES_RPT", "sales_report_", SALES_REPORT_MENU)},
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
    {"code": "SYSTEM_DATA_RESET", "label": "پاک‌سازی اطلاعات (فنی)", "screen": "system_data_reset"},
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
    # R275: صفحهٔ اصلی هم ریبون دارد -- میان‌برِ پرکاربردترین فرم‌هایِ همهٔ ماژول‌ها
    "dashboard": [
        ("SALES_INVOICE", "🧾"),
        ("SALES_ORDER", "📝"),
        ("PURCH_INVOICE", "🛍️"),
        ("PURCH_ORDER", "📋"),
        ("TREASURY_RECEIPT", "💵"),
        ("TREASURY_PAYMENT", "💸"),
        ("GL_JE", "📒"),
        ("INV_RECEIPT", "📥"),
        ("INV_ISSUE", "📤"),
        ("SALES_DOCUMENTS_LIST", "📚"),
        ("PURCH_DOCUMENTS_LIST", "🗃️"),
        ("REPORTS_TRIAL_BALANCE", "⚖️"),
        ("MY_TASKS", "📌"),
    ],
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
    # R274: میان‌برهایِ ریبونِ ماژول‌هایِ بها/دارایی/تولید، هم‌الگو با بقیهٔ ماژول‌ها
    "COSTING": [
        ("COST_DASHBOARD", "📊"),
        ("COST_VALUATION", "💰"),
        ("COST_LAYERS", "🧱"),
        ("COST_HISTORY", "🕘"),
        ("COST_COGS", "🧾"),
        ("COST_REPLACEMENT", "🔁"),
        ("COST_RECALC", "🧮"),
        ("COST_CENTER", "🏢"),
    ],
    "FA": [
        ("FA_DASHBOARD", "📊"),
        ("FA_ASSETS", "🏭"),
        ("FA_DEPRECIATION", "📉"),
        ("FA_CIP", "🏗️"),
        ("FA_PHYSICAL", "🔳"),
        ("FA_RPT_REGISTER", "📒"),
        ("FA_RPT_DEPRECIATION", "📋"),
    ],
    "PRD": [
        ("PRD_DASHBOARD", "📊"),
        ("PRD_ORDERS", "🏭"),
        ("PRD_PLANNING", "🧠"),
        ("PRD_MASTER", "🧩"),
        ("PRD_COSTING", "🧮"),
        ("PRD_RPT_ORDERS", "📋"),
        ("PRD_RPT_COST", "💵"),
        ("PRD_RPT_WIP", "⏳"),
    ],
    "SALES": [
        ("SALES_ASSISTANT", "🧠"),
        ("SALES_ORDER", "📝"),
        ("SALES_INVOICE", "🧾"),
        ("SALES_RETURN", "↩️"),
        ("SALES_CONSIGNMENT_OUT", "🤝"),
        ("SALES_DOCUMENTS_LIST", "📚"),
        ("SALES_PRICING", "🏷️"),
        ("SALES_POS_SALE", "🛒"),
        ("SALES_POS_APPROVAL", "🧾"),
        ("SALES_ECOMMERCE", "🌐"),
        ("SALES_COLD_DISTRIBUTION", "🧊"),
        ("SALES_DISTRIBUTION", "🚚"),
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
        ("REPORTS_SALES_BY_ITEM", "🛍️"),
        ("REPORTS_CUSTOMER_PROFIT", "💹"),
        ("REPORTS_SALES_FORECAST", "🔮"),
    ],
    "SETTINGS": [],
}

# صفحاتی که در NAV_ITEMS نیامده‌اند چون به‌صورتِ زیرتب/زیرزیرتبِ «تنظیماتِ
# سیستم» (system_settings.py) درونِ یک صفحه‌ی واحد جمع شده‌اند — این‌ها هم
# باید در جدولِ دسترسیِ نقش‌ها قابلِ‌تنظیم باشند.
SETTINGS_SUB_FORMS = [
    ("accounting_coding", "کدینگ حساب‌ها"),
    ("detail_level_digits", "تعداد رقم سطوح تفصیلی"),
    ("financial_statement_mapping", "تنظیمات صورت‌های مالی"),
    ("companies", "شرکت‌ها"),
    ("languages", "زبان‌ها"),
    ("currencies", "ارزها"),
    ("fiscal_years", "سال‌های مالی"),
    ("users", "کاربران"),
    ("roles", "نقش‌ها و دسترسی‌ها"),
    ("field_labels", "عنوان فیلدها"),
    ("translations", "ترجمه‌ها"),
    ("workflow_designer", "طراحی گردش کار"),
    ("audit_log", "امنیت (رخدادنگار)"),
    ("payroll_settings", "تنظیمات حقوق و دستمزد"),
    # R272: دسترسیِ جداگانهٔ هر تبِ «تنظیماتِ سیستم» (تب‌هایِ دارایی/تولید/بها با فرمِ ماژولِ خودشان)
    ("treasury_settings", "تنظیمات خزانه‌داری"),
    ("inventory_settings", "تنظیمات انبار و موجودی"),
    ("commercial_settings", "تنظیمات مدیریت بازرگانی"),
    ("report_settings", "تنظیمات چاپ و گزارش‌ها"),
]

# طبقِ بازخوردِ صریحِ کاربر («منویِ اصلی شلوغ شده»): مرکزِ رسانه دیگر
# آیتمِ مستقلِ NAV_ITEMS نیست -- یکی از تب‌هایِ commercial_online_sales_hub
# است، ولی همچنان فرم‌کدِ خودش (media_center) را برایِ ذخیره‌یِ فایل/
# تعیینِ دسترسی نگه می‌دارد -- پس این‌جا (زیرِ ماژولِ SALES، نه SETTINGS)
# به‌صورتِ دستی به فهرستِ فرم‌ها اضافه می‌شود.
_EMBEDDED_HUB_SUB_FORMS: list[tuple[str, str, str]] = [
    ("media_center", "SALES", "مرکز رسانه"),
    # R265: دسترسی‌هایِ جداگانهٔ عملیاتِ دارایی (و فرمِ گردشِ کارِ تأییدِ هرکدام) -- صفحهٔ «دارایی‌ها» این‌ها را چک می‌کند
    ("fa_capitalize", "FA", "دارایی: سرمایه‌ای‌کردن"), ("fa_transfer", "FA", "دارایی: انتقال"),
    ("fa_reclassify", "FA", "دارایی: تغییر طبقه"), ("fa_improve", "FA", "دارایی: افزایش سرمایه‌ای/تعمیر"),
    ("fa_impair", "FA", "دارایی: کاهش ارزش"), ("fa_revalue", "FA", "دارایی: تجدید ارزیابی"),
    ("fa_sell", "FA", "دارایی: فروش"), ("fa_scrap", "FA", "دارایی: اسقاط"), ("fa_dispose", "FA", "دارایی: واگذاری/حذف"),
    ("fa_split_merge", "FA", "دارایی: تقسیم/ادغام/جزء"), ("fa_cost_view", "FA", "دارایی: مشاهدهٔ بها"),
    ("fa_cost_adjust", "FA", "دارایی: ثبت بهای تحصیل"),
    # R270: دسترسی‌هایِ جداگانهٔ تولید (بندِ ۳۶) -- «مشاهده/ایجاد/ویرایشِ دستور» همان VIEW/CREATE/EDITِ prd_orders است
    ("prd_release", "PRD", "تولید: صدور و رزرو"), ("prd_consume", "PRD", "تولید: مصرف مواد و ثبت کار"),
    ("prd_complete", "PRD", "تولید: ثبت تولید و اتمام"), ("prd_close", "PRD", "تولید: بستن دستور"),
    ("prd_cost_view", "PRD", "تولید: مشاهدهٔ بها"), ("prd_cost_adjust", "PRD", "تولید: اصلاح بها/بازگشایی"),
    ("prd_bom", "PRD", "تولید: مدیریت فهرست مواد (BOM)"), ("prd_routing", "PRD", "تولید: مدیریت مسیر تولید"),
    ("prd_allocation", "PRD", "تولید: مدیریت سرشکن هزینه"),
    # R281: دسترسی‌های CRM بدون صفحهٔ جدا (CRM_EXPORT = اکشن EXPORT روی هر فرم CRM؛ CRM_ADMIN = فرم crm_settings)
    ("crm_activities", "CRM", "ارتباط با مشتری: فعالیت‌ها و پیگیری‌ها"), ("crm_assign", "CRM", "ارتباط با مشتری: واگذاری سرنخ و فرصت"),
]

# نگاشتِ کدِ ماژولِ آیتم‌هایِ سطحِ بالایی که خودشان زیرگروه ندارند — فقط
# «داشبورد» با این قاعده مچ نمی‌شود (کدِ خودش با کدِ ماژولش یکی نیست).
_TOP_LEVEL_MODULE_CODE_OVERRIDE = {
    "dashboard": "DASH",
    "SYSTEM_BACKUP": "SETTINGS",
    "SYSTEM_DATA_RESET": "SETTINGS",
}


def flatten_nav_items() -> list[dict]:
    """همهٔ آیتم‌های برگ (دارای «screen») را، در هر عمقی از تودرتویی
    زیرمنوها، برمی‌گرداند — منوی «گزارش‌ها» مثلاً حالا یک لایهٔ زیرمنوی
    ماژول (مثل «حسابداری») هم دارد، پس بازگشتی طی می‌شود."""
    flat: list[dict] = []

    def _walk(items: list[dict]) -> None:
        for item in items:
            if item.get("children"):
                _walk(item["children"])
            else:
                flat.append(item)

    _walk(NAV_ITEMS)
    return flat


def flatten_nav_items_with_breadcrumb() -> list[tuple[str, str, str]]:
    """مشابه flatten_nav_items، ولی به‌ازای هر آیتم برگ، مسیر کامل
    منو (breadcrumb) را هم برمی‌گرداند — طبق نیاز جستجوی سراسری
    (کادر ازپیش‌موجود ولی تا امروز بی‌اتصال «جستجو در سیستم» در
    نوار بالایی): وقتی چند آیتم برگ در زیرمنوهای مختلف برچسب یکسان
    دارند (مثلاً «نگاشت حساب‌ها» هم زیر انبار هم زیر بازرگانی است)،
    این مسیر برای نمایش متمایز و ناوبری درست لازم است."""
    result: list[tuple[str, str, str]] = []

    def _walk(items: list[dict], path: list[str]) -> None:
        for item in items:
            if item.get("children"):
                _walk(item["children"], path + [item["label"]])
            elif item.get("screen"):
                breadcrumb = " › ".join(path + [item["label"]]) if path else item["label"]
                result.append((item["code"], item["label"], breadcrumb))

    _walk(NAV_ITEMS, [])
    return result


def build_form_catalog() -> list[tuple[str, str, str]]:
    """(form_code, module_code, label) برای همهٔ صفحات برنامه — از روی
    NAV_ITEMS + زیرتب‌های «تنظیمات سیستم» — تک منبع حقیقتی که
    services/roles.py برای ساخت جدول دسترسی نقش‌ها استفاده می‌کند.
    ماژول هر فرم همیشه کد آیتم سطح‌بالا است، حتی اگر خود فرم چند لایه
    زیر زیرمنوهای داخلی (مثل «گزارش‌ها ← حسابداری») تودرتو باشد."""
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
    for code, module_code, label in _EMBEDDED_HUB_SUB_FORMS:
        catalog.append((code, module_code, label))
    # R232: یک صفحه می‌تواند از دو منو باز شود (مثلاً تاییدِ انبار در خرید و فروش) -- یک فرمِ دسترسی
    seen: set[str] = set()
    return [row for row in catalog if not (row[0] in seen or seen.add(row[0]))]
