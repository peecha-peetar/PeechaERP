-- پیچا R248: مدیریتِ محلِ انبار و نقشهٔ تعاملی -- فقط افزایشی.
-- معماری: inv.bin_locations از قبل سلسله‌مراتبی است (parent_bin_location_id) و موجودی/دفترِ انبار
-- به bin_location_id وصل‌اند؛ پس جدولِ تازه‌ای ساخته نمی‌شود و همین جدول توسعه می‌یابد:
--   سطح = bin_type_code موجود (AREA=Zone، AISLE، RACK، SHELF=Level، BIN)
--   location_type_code = نوعِ کاربردیِ محل (دریافت، QC، قرنطینه، ...)
-- انواعِ تازهٔ انبار (مرکزِ توزیع، سردخانه، گرمخانه): قیدِ CHECK با مجموعهٔ بزرگ‌تر جایگزین می‌شود (داده دست نمی‌خورد).
-- بازگشت (rollback): ستون‌هایِ زیر را DROP COLUMN IF EXISTS و قیدِ نوعِ انبار را به فهرستِ قبلی برگردانید.
ALTER TABLE inv.bin_locations
    ADD COLUMN IF NOT EXISTS location_code VARCHAR(120) NULL,
    ADD COLUMN IF NOT EXISTS location_type_code VARCHAR(20) NULL,
    ADD COLUMN IF NOT EXISTS description VARCHAR(500) NULL,
    ADD COLUMN IF NOT EXISTS status_code VARCHAR(15) NOT NULL DEFAULT 'ACTIVE',
    ADD COLUMN IF NOT EXISTS level_number SMALLINT NULL,
    ADD COLUMN IF NOT EXISTS direction VARCHAR(10) NULL,
    ADD COLUMN IF NOT EXISTS width_m NUMERIC(10, 3) NULL,
    ADD COLUMN IF NOT EXISTS length_m NUMERIC(10, 3) NULL,
    ADD COLUMN IF NOT EXISTS height_m NUMERIC(10, 3) NULL,
    ADD COLUMN IF NOT EXISTS max_weight_kg NUMERIC(14, 3) NULL,
    ADD COLUMN IF NOT EXISTS max_volume_m3 NUMERIC(14, 3) NULL,
    ADD COLUMN IF NOT EXISTS temperature_min_c NUMERIC(5, 2) NULL,
    ADD COLUMN IF NOT EXISTS temperature_max_c NUMERIC(5, 2) NULL,
    ADD COLUMN IF NOT EXISTS allow_putaway BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS allow_replenishment BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS is_damaged BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS map_x NUMERIC(10, 2) NULL,
    ADD COLUMN IF NOT EXISTS map_y NUMERIC(10, 2) NULL,
    ADD COLUMN IF NOT EXISTS map_z NUMERIC(10, 2) NULL,
    ADD COLUMN IF NOT EXISTS map_width NUMERIC(10, 2) NULL,
    ADD COLUMN IF NOT EXISTS map_height NUMERIC(10, 2) NULL,
    ADD COLUMN IF NOT EXISTS map_rotation NUMERIC(6, 2) NULL;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_inv_bin_locations_status') THEN
        ALTER TABLE inv.bin_locations ADD CONSTRAINT ck_inv_bin_locations_status
            CHECK (status_code IN ('ACTIVE', 'INACTIVE', 'BLOCKED', 'FULL', 'RESERVED', 'QUARANTINE', 'MAINTENANCE'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_inv_bin_locations_capacity') THEN
        ALTER TABLE inv.bin_locations ADD CONSTRAINT ck_inv_bin_locations_capacity
            CHECK ((width_m IS NULL OR width_m >= 0) AND (length_m IS NULL OR length_m >= 0) AND (height_m IS NULL OR height_m >= 0)
                   AND (max_weight_kg IS NULL OR max_weight_kg >= 0) AND (max_volume_m3 IS NULL OR max_volume_m3 >= 0));
    END IF;
END $$;
UPDATE inv.bin_locations SET status_code = 'INACTIVE' WHERE is_active = FALSE AND status_code = 'ACTIVE';
CREATE UNIQUE INDEX IF NOT EXISTS ux_inv_bin_locations_location_code ON inv.bin_locations (warehouse_id, location_code)
    WHERE location_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_inv_bin_locations_parent ON inv.bin_locations (parent_bin_location_id);

ALTER TABLE inv.warehouses
    ADD COLUMN IF NOT EXISTS width_m NUMERIC(10, 2) NULL,
    ADD COLUMN IF NOT EXISTS length_m NUMERIC(10, 2) NULL,
    ADD COLUMN IF NOT EXISTS height_m NUMERIC(10, 2) NULL,
    ADD COLUMN IF NOT EXISTS description VARCHAR(1000) NULL;
ALTER TABLE inv.warehouses DROP CONSTRAINT IF EXISTS warehouses_warehouse_type_code_check;
ALTER TABLE inv.warehouses ADD CONSTRAINT warehouses_warehouse_type_code_check CHECK (warehouse_type_code IN (
    'GENERAL', 'PROJECT', 'PRODUCTION_LINE', 'QUARANTINE', 'TRANSIT', 'CENTRAL', 'BRANCH', 'STORE', 'RAW_MATERIAL',
    'FINISHED_GOODS', 'SEMI_FINISHED', 'SCRAP', 'CONSIGNMENT', 'VEHICLE', 'RETURNED',
    'DISTRIBUTION', 'COLD_STORAGE', 'HOT_STORAGE'));
