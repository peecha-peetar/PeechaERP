-- طبقِ درخواستِ صریحِ کاربر («ماژولِ پخشِ سرد/گرم + سفارشِ موبایل»):
-- زیرساختِ مشترکِ توزیع -- خودرو به‌عنوانِ انبارِ سیار (از نوعِ انبارِ
-- VEHICLEِ از قبل موجود)، مسیرِ توزیعِ مشتری، و دو کانالِ فروشِ تازه
-- (پخشِ سرد/پیش‌فروش و پخشِ گرم/فروشِ خودرویی). ماژولِ موبایل و
-- زیرساختِ Sync در این مرحله ساخته نمی‌شود -- تصمیمِ معماریِ آن هنوز
-- با کاربر نهایی نشده است.

ALTER TABLE inv.warehouses ADD COLUMN vehicle_plate_number VARCHAR(30) NULL;
ALTER TABLE inv.warehouses ADD COLUMN vehicle_driver_detail_account_id INT NULL
    REFERENCES acc.detail_accounts(detail_account_id);
ALTER TABLE inv.warehouses ADD COLUMN vehicle_capacity_weight_kg NUMERIC(18,3) NULL;
ALTER TABLE inv.warehouses ADD COLUMN vehicle_capacity_volume_m3 NUMERIC(18,3) NULL;

ALTER TABLE comm.customer_profiles ADD COLUMN distribution_route_detail_account_id INT NULL
    REFERENCES acc.detail_accounts(detail_account_id);

ALTER TABLE comm.channels DROP CONSTRAINT channels_channel_type_code_check;
ALTER TABLE comm.channels ADD CONSTRAINT channels_channel_type_code_check
    CHECK (channel_type_code IN ('POS', 'WHOLESALE', 'ONLINE', 'AGENT', 'MARKETPLACE', 'VAN_SALES', 'PRE_SALES'));
