-- R320: طرح حرفه‌ای قالب‌های چاپ (مورد ۱۵) و پیشنهاد مسیر پخش سرد بر اساس موقعیت مشتری (مورد ۱۸).
-- هر دو پشت کلید روشن/خاموش؛ ستون‌های تازه همه اختیاری‌اند و رفتار قبلی را تغییر نمی‌دهند.

INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('REPORT_PRO_TEMPLATES', 'چاپ با طرح حرفه‌ای', 'REPORTING', NULL,
     'فاکتور و سند انبار، وقتی گزارشی برایشان تعریف نشده، با طرح حرفه‌ای (نوار عنوان، جدول راست‌به‌چپ راه‌راه، جعبهٔ جمع، جای امضا و شمارهٔ صفحه) چاپ می‌شوند و گزارش تازه در «تنظیمات › گزارش‌ها» به‌طور پیش‌فرض با همین طرح ساخته می‌شود.')
ON CONFLICT (feature_code) DO NOTHING;

INSERT INTO comm.feature_definitions (feature_code, name, module_scope, requires_feature_code, requires_account_mapping_keys, description) VALUES
    ('DIST_ROUTE_SUGGEST', 'پیشنهاد مسیر پخش سرد بر اساس موقعیت مشتری', 'COMMERCIAL', NULL, NULL,
     'در «تیم پخش»، ترتیب تحویل فاکتورها از روی موقعیت ثبت‌شدهٔ مشتری (آدرس تحویل یا فروشگاه) پیشنهاد می‌شود و فاکتورها و فهرست چاپی راننده به همین ترتیب مرتب می‌شوند؛ ترتیب را می‌توان دستی هم جابه‌جا کرد.')
ON CONFLICT (feature_code) DO NOTHING;

-- نقطهٔ شروع اختیاری مسیر (مثلاً انبار مرکزی) برای هر تیم پخش
ALTER TABLE comm.distribution_runs ADD COLUMN IF NOT EXISTS start_latitude NUMERIC(9, 6);
ALTER TABLE comm.distribution_runs ADD COLUMN IF NOT EXISTS start_longitude NUMERIC(9, 6);
-- ترتیب تحویل در مسیر؛ خالی یعنی هنوز مسیربندی نشده (پس از ردیف‌های مرتب‌شده می‌آید)
ALTER TABLE comm.distribution_run_documents ADD COLUMN IF NOT EXISTS route_seq INTEGER;
