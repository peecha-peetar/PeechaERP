-- پیچا | افزودنِ نوعِ سندِ «انبار» — طبقِ همان الگویِ RECEIPT/PAYMENT/PAYROLL/
-- TANKHAH: سندِ حسابداریِ خودکارِ هر Postِ موفقِ سندِ انبار (inv.stock_documents)
-- با همین entry_type_code ساخته می‌شود تا در فهرست/گزارش قابلِ‌تفکیک باشد.
-- پیش‌نیاز: 003_accounting_core.sql

INSERT INTO acc.journal_entry_types (entry_type_id, code) VALUES
    (9, 'INVENTORY')
ON CONFLICT (entry_type_id) DO NOTHING;
