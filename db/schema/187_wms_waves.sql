-- پیچا R250: برداشتِ موجی (Wave) -- فقط افزایشی.
-- موج = گروهی از وظایفِ برداشتِ یک انبار با ترتیبِ مسیرِ بهینه (wave_sequence).
-- شمارشِ محل از همان inv.cycle_count_sessions (scope_type_code = 'BY_BIN') و inv.cycle_count_lines
-- (که از ابتدا bin_location_id دارد) استفاده می‌کند؛ جدولِ تازه‌ای لازم نیست.
-- بازگشت (rollback): ALTER TABLE inv.warehouse_tasks DROP COLUMN IF EXISTS wave_id, DROP COLUMN IF EXISTS wave_sequence;
--   DROP TABLE IF EXISTS inv.pick_waves;
CREATE TABLE IF NOT EXISTS inv.pick_waves (
    wave_id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    wave_code VARCHAR(30) NOT NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'OPEN' CHECK (status_code IN ('OPEN', 'DONE', 'CANCELLED')),
    path_distance NUMERIC(12, 1) NULL,
    created_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    completed_at TIMESTAMP NULL,
    CONSTRAINT uq_inv_pick_waves UNIQUE (company_id, wave_code)
);
ALTER TABLE inv.warehouse_tasks
    ADD COLUMN IF NOT EXISTS wave_id INT NULL REFERENCES inv.pick_waves(wave_id),
    ADD COLUMN IF NOT EXISTS wave_sequence SMALLINT NULL;
CREATE INDEX IF NOT EXISTS ix_inv_warehouse_tasks_wave ON inv.warehouse_tasks (wave_id, wave_sequence);
