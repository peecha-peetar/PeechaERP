-- پیچا R226: قفلِ مقدارِ فاکتور پس از تاییدِ رسیدِ کالا توسطِ انباردار دیگر
-- تنظیمی نیست و همیشه اعمال می‌شود (انبار مسئولِ تعداد است).
DELETE FROM comm.company_features WHERE feature_code = 'RECEIPT_LOCKS_INVOICE_QUANTITY';
DELETE FROM comm.feature_definitions WHERE feature_code = 'RECEIPT_LOCKS_INVOICE_QUANTITY';
