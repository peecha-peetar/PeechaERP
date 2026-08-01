-- پیچا | طبقِ درخواستِ صریح: حذفِ کاملِ ویژگیِ «تنظیمِ سندِ اتوماتیک»/«انواعِ
-- سند» — این جدول‌ها (اگر رویِ این پایگاه‌داده از migrationهایِ قبلی ساخته
-- شده باشند) حذف می‌شوند؛ فرمِ دریافت/پرداخت دوباره از رویِ نگاشتِ حساب‌ها
-- + طرفِ‌حسابِ آزاد کار می‌کند (services/treasury.list_counterparty_account_options).

DROP TABLE IF EXISTS treasury.document_type_details;
DROP TABLE IF EXISTS treasury.document_types;
