-- پیچا | نوعِ سندِ تازه برایِ فرمِ «تنخواه‌گردان» (هم‌الگو با ۰۲۲:
-- RECEIPT/PAYMENT) — تا اسنادِ تنخواه در فهرستِ جداگانه‌یِ خودشان
-- قابلِ‌تفکیک باشند، هرچند از همان روش‌ها/تنظیماتِ فرمِ پرداخت استفاده
-- می‌کنند.
INSERT INTO acc.journal_entry_types (entry_type_id, code) VALUES
    (8, 'TANKHAH')
ON CONFLICT (entry_type_id) DO NOTHING;
