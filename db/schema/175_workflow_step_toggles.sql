-- پیچا R230: مراحلِ اختیاریِ گردشِ کار (برایِ مجموعه‌هایِ کوچک).
-- PURCHASE_ORDER_SKIP_POST: سفارشِ خرید بدونِ «ثبتِ نهایی» به تاییدِ رسیدِ انبار برسد
--   (پیش‌فرض خاموش: فقط سفارشِ ثبتِ‌نهایی‌شده در فرمِ تاییدِ رسید دیده می‌شود).
-- CONSIGNMENT_WAREHOUSE_APPROVAL: امانیِ ورودی/خروجی پیش از ثبتِ نهایی به تاییدِ انباردار برسد.
INSERT INTO comm.feature_definitions (feature_code, name, module_scope, requires_feature_code, requires_account_mapping_keys) VALUES
    ('PURCHASE_ORDER_SKIP_POST', 'بی‌نیازی از ثبتِ نهاییِ سفارشِ خرید پیش از تاییدِ رسیدِ انبار', 'COMMERCIAL', 'PURCHASE_ORDER_GOODS_RECEIPT', NULL),
    ('CONSIGNMENT_WAREHOUSE_APPROVAL', 'تاییدِ انباردار برایِ امانیِ ورودی/خروجی پیش از ثبتِ نهایی', 'COMMERCIAL', NULL, NULL)
ON CONFLICT (feature_code) DO NOTHING;
