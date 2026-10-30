-- پیچا | طبقِ درخواستِ صریح: امکانِ انتخابِ انبارِ مستقل برایِ هر ردیفِ
-- سندِ بازرگانی (سفارش/پیش‌فاکتور/فاکتور/برگشت، هم فروش هم خرید) —
-- به‌جایِ یک انبارِ واحد در هدر، تا حتی یک کالا بتواند هم‌زمان در چند
-- ردیف با انبارهایِ مختلف باشد و به‌ازایِ هر انبار یک حوالهٔ جداگانه
-- صادر شود. به‌صورتِ Toggleِ اختیاری (پیش‌فرض خاموش = روشِ قدیمِ هدر).
-- خودِ فیلدِ انبارِ هدر همچنان می‌ماند و به‌عنوانِ پیش‌فرضِ ردیفِ تازه
-- استفاده می‌شود.

ALTER TABLE comm.commercial_document_lines
    ADD COLUMN warehouse_id INT NULL REFERENCES inv.warehouses(warehouse_id);

INSERT INTO comm.feature_definitions (feature_code, name, module_scope, requires_feature_code, requires_account_mapping_keys) VALUES
    ('PER_LINE_WAREHOUSE', 'انتخابِ انبارِ جداگانه برایِ هر ردیف (به‌جایِ هدر)', 'INVENTORY', NULL, NULL);
