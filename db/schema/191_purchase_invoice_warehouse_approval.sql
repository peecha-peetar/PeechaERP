-- پیچا R255: فاکتورِ خریدِ مستقیم (بدونِ سفارشِ رسیده) پیش از ثبتِ نهایی به تاییدِ رسیدِ انباردار برسد (اختیاری).
INSERT INTO comm.feature_definitions (feature_code, name, module_scope, requires_feature_code, requires_account_mapping_keys) VALUES
    ('PURCHASE_INVOICE_WAREHOUSE_APPROVAL', 'تاییدِ رسیدِ انباردار برایِ فاکتورِ خریدِ مستقیم پیش از ثبتِ نهایی', 'COMMERCIAL', NULL, NULL)
ON CONFLICT (feature_code) DO NOTHING;
