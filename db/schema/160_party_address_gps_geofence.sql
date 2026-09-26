-- پیچا | چندآدرسیِ واقعی + GeoFence (R216، بخشِ ۲) -- comm.party_addresses
-- از قبل چندآدرسه بود (BILLING/SHIPPING/PICKUP) ولی نه GPS داشت نه انواعِ
-- موردِ نیازِ پخشِ مویرگی (دفتر/فروشگاه/انبار/تحویل/مرجوعی). طبقِ اصلِ
-- «بدونِ سیستمِ موازی»: همان جدول را گسترش می‌دهیم، جدولِ تازه نمی‌سازیم.

ALTER TABLE comm.party_addresses
    DROP CONSTRAINT party_addresses_address_type_code_check;

ALTER TABLE comm.party_addresses
    ADD CONSTRAINT party_addresses_address_type_code_check
        CHECK (address_type_code IN ('OFFICE', 'STORE', 'WAREHOUSE', 'DELIVERY', 'BILLING', 'RETURN'));

ALTER TABLE comm.party_addresses
    ADD COLUMN gps_latitude NUMERIC(9, 6) NULL,
    ADD COLUMN gps_longitude NUMERIC(9, 6) NULL,
    -- طبقِ اصلِ صریح («ویزیتور فقط زمانی می‌تواند ویزیت را ثبت کند که در
    -- محدودهٔ فروشگاه باشد»): NULL یعنی بدونِ اعمالِ محدودیت.
    ADD COLUMN geofence_radius_meters INT NULL
        CHECK (geofence_radius_meters IS NULL OR geofence_radius_meters > 0);
