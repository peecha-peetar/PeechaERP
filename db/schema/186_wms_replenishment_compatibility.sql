-- پیچا R249: تأمینِ مجددِ جبههٔ برداشت، رزروِ وظیفهٔ برداشت و سازگاریِ کالا با محل -- فقط افزایشی.
-- ۱) inv.item_storage_profiles: شرایطِ نگهداریِ کالا (بازهٔ دما، کلاسِ خطر، شکستنی، نوعِ محلِ الزامی).
--    جدولِ جدا (یک‌به‌یک با inv.items) تا مدل/فرمِ موجودِ کالا دست نخورد.
-- ۲) inv.bin_locations.allows_hazardous: محلِ مجاز برایِ کالایِ خطرناک (به زیرمحل‌ها ارث می‌رسد).
-- ۳) inv.location_replenishment_rules: حداقل/حداکثرِ هر کالا در هر محلِ برداشت.
-- ۴) inv.warehouse_tasks: نوعِ تازهٔ REPLENISH (قیدِ CHECK با مجموعهٔ بزرگ‌تر جایگزین می‌شود).
-- رزروِ وظیفهٔ برداشت در همان inv.stock_reservations موجود نوشته می‌شود (source_type_code = 'WMS_PICK_TASK')؛
-- ستونِ quantity_reservedِ مانده (موتورِ انبار) دست نمی‌خورد.
-- بازگشت (rollback): DROP TABLE IF EXISTS inv.location_replenishment_rules, inv.item_storage_profiles;
--   ALTER TABLE inv.bin_locations DROP COLUMN IF EXISTS allows_hazardous; قیدِ نوعِ وظیفه را به ('PUTAWAY','PICK') برگردانید.
CREATE TABLE IF NOT EXISTS inv.item_storage_profiles (
    item_id INT PRIMARY KEY REFERENCES inv.items(item_id) ON DELETE CASCADE,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    temperature_min_c NUMERIC(5, 2) NULL,
    temperature_max_c NUMERIC(5, 2) NULL,
    hazard_class_code VARCHAR(20) NULL CHECK (hazard_class_code IN (
        'EXPLOSIVE', 'GAS', 'FLAMMABLE_LIQUID', 'FLAMMABLE_SOLID', 'OXIDIZER', 'TOXIC', 'RADIOACTIVE', 'CORROSIVE', 'MISC')),
    is_fragile BOOLEAN NOT NULL DEFAULT FALSE,
    required_location_type_code VARCHAR(20) NULL,
    notes VARCHAR(500) NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT ck_inv_item_storage_temperature CHECK (
        temperature_min_c IS NULL OR temperature_max_c IS NULL OR temperature_min_c <= temperature_max_c)
);

ALTER TABLE inv.bin_locations ADD COLUMN IF NOT EXISTS allows_hazardous BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS inv.location_replenishment_rules (
    rule_id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    bin_location_id INT NOT NULL REFERENCES inv.bin_locations(bin_location_id),
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    min_quantity NUMERIC(18, 6) NOT NULL CHECK (min_quantity >= 0),
    max_quantity NUMERIC(18, 6) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT ck_inv_replenishment_minmax CHECK (max_quantity > min_quantity),
    CONSTRAINT uq_inv_replenishment_rule UNIQUE (bin_location_id, item_id)
);

ALTER TABLE inv.warehouse_tasks DROP CONSTRAINT IF EXISTS warehouse_tasks_task_type_code_check;
ALTER TABLE inv.warehouse_tasks ADD CONSTRAINT warehouse_tasks_task_type_code_check
    CHECK (task_type_code IN ('PUTAWAY', 'PICK', 'REPLENISH'));
ALTER TABLE inv.warehouse_tasks ADD COLUMN IF NOT EXISTS replenishment_rule_id INT NULL
    REFERENCES inv.location_replenishment_rules(rule_id);
CREATE INDEX IF NOT EXISTS ix_inv_warehouse_tasks_open ON inv.warehouse_tasks (company_id, task_type_code, status_code);
