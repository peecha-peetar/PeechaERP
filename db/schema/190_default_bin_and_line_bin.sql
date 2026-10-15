-- پیچا R253: مکانِ پیش‌فرضِ قابلِ‌تغییرِ انبار و ستونِ «مکان» در ردیفِ اسنادِ بازرگانی (فاکتور/سفارشِ خرید) -- فقط افزایشی.
-- ۱) inv.warehouses.default_bin_location_id: اگر پر باشد، ردیفِ بی‌محلِ اسنادِ انبار در همین محل ثبت می‌شود؛
--    خالی = رفتارِ قبلی (محلِ «GENERAL» یا اولین محلِ انبار).
-- ۲) comm.commercial_document_lines.bin_location_id: محلِ ورود/خروجِ همان ردیف که هنگامِ صدورِ سندِ انبار
--    به ردیفِ سندِ انبار منتقل می‌شود.
-- بازگشت (rollback): DROP COLUMN IF EXISTS هر دو ستون.
ALTER TABLE inv.warehouses ADD COLUMN IF NOT EXISTS default_bin_location_id INT NULL REFERENCES inv.bin_locations(bin_location_id);
ALTER TABLE comm.commercial_document_lines ADD COLUMN IF NOT EXISTS bin_location_id INT NULL REFERENCES inv.bin_locations(bin_location_id);
