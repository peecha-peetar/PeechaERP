-- طبقِ درخواستِ صریح («در تنظیمات هم قابلِ تغییر باشد که آیا فاکتور و
-- ضمائم را بتوان اصلاح کرد یا نه»): Toggleِ سراسریِ سطحِ شرکت -- وقتی
-- خاموش است، حتی مدیر (سوپروایزر/ادمین) هم اجازه‌یِ اصلاحِ فاکتورِ
-- ثبت‌شده را ندارد.
INSERT INTO comm.feature_definitions (feature_code, name, module_scope, requires_feature_code, requires_account_mapping_keys) VALUES
    ('ALLOW_EDIT_POSTED_INVOICE', 'اجازه‌یِ اصلاحِ فاکتورِ ثبت‌شده (توسطِ مدیر)', 'GENERAL', NULL, NULL);
