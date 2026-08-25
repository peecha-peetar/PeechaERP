-- پیچا | رفعِ باگِ واقعی: اگر حسابِ «پیش‌پرداختِ تنخواه» (نگاشتِ
-- PETTY_CASH_ADVANCE) خودش، جدا از بُعدِ تنخواه‌دار، بُعد/گروهِ شخصِ
-- دیگری هم الزامی کرده باشد، افتتاح/بستنِ تنخواه قبلاً همیشه با خطایِ
-- «انتخابِ گروه‌هایِ تفصیلیِ الزامی فراموش شده است» رد می‌شد — چون
-- open_fund/close_fund فقط بُعدِ تنخواه‌دار را می‌فرستادند. این جدول
-- همان انتخاب‌هایِ اضافیِ هنگامِ افتتاح را نگه می‌دارد تا هنگامِ بستن هم
-- دوباره (بدونِ پرسیدنِ دوباره از کاربر) به همان سند اعمال شود.

CREATE TABLE treasury.petty_cash_fund_extra_details (
    fund_id            INT NOT NULL REFERENCES treasury.petty_cash_funds(fund_id) ON DELETE CASCADE,
    dimension_type_id  INT NOT NULL REFERENCES acc.detail_dimension_types(dimension_type_id),
    detail_account_id  INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    PRIMARY KEY (fund_id, dimension_type_id)
);
