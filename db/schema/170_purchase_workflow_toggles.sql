-- پیچا | طبقِ گزارشِ صریحِ کاربر (R224):
-- RECEIPT_LOCKS_INVOICE_QUANTITY: بعدِ تاییدِ رسیدِ کالا توسطِ انباردار، مقدارِ
--   ردیف‌هایِ فاکتورِ حاصل از همان سفارش قابلِ‌تغییر/حذف نیست.
-- PURCHASE_INVOICE_SKIP_APPROVAL: مرحله‌یِ جداگانهٔ تصویبِ مدیر برایِ فاکتور/
--   پیش‌فاکتورِ خرید حذف می‌شود (تاییدِ کاربر برایِ ثبتِ نهایی کافی است).
-- INVOICE_ONE_STEP_POST: در فاکتورِ خرید/فروش، دکمهٔ تایید -- برایِ کاربرِ مدیر
--   -- بلافاصله نحوه‌یِ تسویه را می‌پرسد و سند را ثبتِ نهایی می‌کند.
INSERT INTO comm.feature_definitions (feature_code, name, module_scope, requires_feature_code, requires_account_mapping_keys) VALUES
    ('RECEIPT_LOCKS_INVOICE_QUANTITY', 'قفلِ مقدارِ فاکتور پس از تاییدِ رسیدِ کالا توسطِ انباردار', 'COMMERCIAL', 'PURCHASE_ORDER_GOODS_RECEIPT', NULL),
    ('PURCHASE_INVOICE_SKIP_APPROVAL', 'بی‌نیازی از مرحلهٔ تصویبِ مدیر برایِ فاکتور/پیش‌فاکتورِ خرید', 'COMMERCIAL', NULL, NULL),
    ('INVOICE_ONE_STEP_POST', 'ثبتِ یک‌مرحله‌ایِ فاکتور (تایید + تسویه + ثبتِ نهایی با یک دکمه، برایِ مدیر)', 'COMMERCIAL', NULL, NULL);
