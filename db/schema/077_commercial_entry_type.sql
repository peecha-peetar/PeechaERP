-- پیچا | افزودنِ نوعِ سندِ «بازرگانی» — طبقِ همان الگویِ INVENTORY: سندِ
-- حسابداریِ خودکارِ هر Postِ موفقِ comm.commercial_documents با همین
-- entry_type_code ساخته می‌شود تا در فهرست/گزارش قابلِ‌تفکیک باشد.
-- پیش‌نیاز: 003_accounting_core.sql

INSERT INTO acc.journal_entry_types (entry_type_id, code) VALUES
    (10, 'COMMERCIAL')
ON CONFLICT (entry_type_id) DO NOTHING;
