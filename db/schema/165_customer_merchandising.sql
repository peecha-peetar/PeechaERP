-- پیچا | اطلاعاتِ فروشگاهی/Merchandising (R219، بخشِ ۱۰) -- ماهول‌سازیِ
-- جداگانه (نه ستون‌هایِ بیشتر رویِ customer_profiles که دارد بزرگ
-- می‌شود)، چون فقط برایِ مشتریانِ نوعِ فروشگاه معنا دارد. عکس‌ها از همان
-- سازوکارِ عمومیِ پیوستِ حساب‌هایِ تفصیلی استفاده می‌کنند (بدونِ سیستمِ
-- موازی). محصولاتِ پرفروش/کم‌فروش عمداً این‌جا نیست -- از دادهٔ واقعیِ
-- فروش محاسبه می‌شود (summarize_customer_purchases، از قبل موجود).

CREATE TABLE comm.customer_merchandising (
    customer_detail_account_id INT PRIMARY KEY REFERENCES acc.detail_accounts(detail_account_id),
    store_area_sqm NUMERIC(10, 1) NULL CHECK (store_area_sqm IS NULL OR store_area_sqm >= 0),
    checkout_count SMALLINT NULL CHECK (checkout_count IS NULL OR checkout_count >= 0),
    fridge_count SMALLINT NULL CHECK (fridge_count IS NULL OR fridge_count >= 0),
    shelf_count SMALLINT NULL CHECK (shelf_count IS NULL OR shelf_count >= 0),
    available_brands VARCHAR(500) NULL,
    competitor_brands VARCHAR(500) NULL,
    layout_status_code VARCHAR(15) NULL
        CHECK (layout_status_code IN ('EXCELLENT', 'GOOD', 'AVERAGE', 'POOR')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by_user_id INT NULL REFERENCES sec.users(user_id)
);
