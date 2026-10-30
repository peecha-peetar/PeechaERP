-- طبقِ ادامه‌یِ اولویت‌بندی (بخشِ ۵ -- عملیاتی: «نگهبانِ اتصال»): تیکِ
-- دوره‌ایِ اتوسینکِ فروشِ اینترنتی/پستِ خودکار (شل) شکستِ هر اتصال را
-- کاملاً بی‌صدا رد می‌کند -- هیچ اثری از یک توکن/رمزِ منقضی‌شده در
-- دیتابیس ثبت نمی‌شود تا کاربر بفهمد. این دو ستون شمارندهٔ شکستِ
-- پیاپی و آخرین پیامِ خطا را نگه می‌دارند تا صفحه‌یِ «نگهبانِ اتصال»
-- بتواند اتصال‌هایِ ناسالم را نشان دهد.
ALTER TABLE comm.marketplace_connections ADD COLUMN consecutive_failure_count INT NOT NULL DEFAULT 0;
ALTER TABLE comm.marketplace_connections ADD COLUMN last_error_message VARCHAR(500);
ALTER TABLE comm.marketplace_connections ADD COLUMN last_checked_at TIMESTAMPTZ;

ALTER TABLE comm.social_connections ADD COLUMN consecutive_failure_count INT NOT NULL DEFAULT 0;
ALTER TABLE comm.social_connections ADD COLUMN last_error_message VARCHAR(500);
ALTER TABLE comm.social_connections ADD COLUMN last_checked_at TIMESTAMPTZ;
