-- ردِ محلِ فعلیِ نگه‌داریِ چکِ دریافتی (نزدِ کدام صندوق/بانکِ مشخص) —
-- پیش‌نیازِ زنجیره‌یِ ۷مرحله‌ایِ چرخه‌یِ چکِ دریافتی (انتقال بینِ صندوق‌ها،
-- واگذاری به بانک، اعلامِ وصول، برگشت از بانک به صندوق، …): هر مرحله
-- بستانکارِ سندش را از رویِ همینِ دو ستون (نه یک کلیدِ نگاشتِ ثابت)
-- می‌خواند تا مراحل زنجیره‌ای‌شان مستقل از تنظیماتِ حساب همدیگر باشد.

ALTER TABLE treasury.received_checks
    ADD COLUMN current_location_account_id        INT NULL REFERENCES acc.chart_of_accounts(account_id),
    ADD COLUMN current_location_detail_account_id  INT NULL REFERENCES acc.detail_accounts(detail_account_id);
