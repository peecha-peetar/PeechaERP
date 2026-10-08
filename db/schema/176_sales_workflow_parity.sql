-- پیچا R232: هم‌ترازیِ گردشِ کارِ فروش با خرید (همه پیش‌فرض خاموش -- رفتارِ فعلیِ فروش تغییری نمی‌کند).
-- SALES_ORDER_WAREHOUSE_ISSUE: تاییدِ حوالهٔ انبار (مقدارِ تحویلی، انبارِ ردیف، بچ/سریال) توسطِ انباردار پیش از تبدیل به فاکتور.
-- SALES_ORDER_SKIP_POST: سفارشِ فروش بدونِ «ثبتِ نهایی» به تاییدِ انبار برسد.
-- SALES_ORDER_MANAGER_APPROVAL / SALES_INVOICE_MANAGER_APPROVAL: تصویبِ مدیر پیش از ثبتِ نهایی.
INSERT INTO comm.feature_definitions (feature_code, name, module_scope, requires_feature_code, requires_account_mapping_keys) VALUES
    ('SALES_ORDER_WAREHOUSE_ISSUE', 'مرحلهٔ جداگانهٔ تاییدِ حوالهٔ انبار برایِ سفارشِ فروش (توسطِ انباردار، پیش از تبدیل به فاکتور)', 'COMMERCIAL', NULL, NULL),
    ('SALES_ORDER_SKIP_POST', 'بی‌نیازی از ثبتِ نهاییِ سفارشِ فروش پیش از تاییدِ حوالهٔ انبار', 'COMMERCIAL', 'SALES_ORDER_WAREHOUSE_ISSUE', NULL),
    ('SALES_ORDER_MANAGER_APPROVAL', 'تصویبِ مدیر برایِ سفارشِ فروش پیش از ثبتِ نهایی', 'COMMERCIAL', NULL, NULL),
    ('SALES_INVOICE_MANAGER_APPROVAL', 'تصویبِ مدیر برایِ فاکتور/پیش‌فاکتورِ فروش پیش از ثبتِ نهایی', 'COMMERCIAL', NULL, NULL)
ON CONFLICT (feature_code) DO NOTHING;
