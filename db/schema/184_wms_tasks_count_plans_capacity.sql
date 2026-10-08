-- پیچا R247 -- فقط افزایشی؛ هیچ ستون/داده‌یِ موجودی تغییر یا حذف نمی‌شود.
-- ۱) inv.cost_adjustment_log: اصلاحِ بهایِ خرید فقط میانگینِ بهایِ مانده را عوض می‌کند و تاریخ‌دار
--    ثبت نمی‌شد؛ بدونِ آن ارزشِ تاریخیِ موجودی (از دفترِ انبار) با مانده نمی‌خواند. فقط لاگ است.
-- ۲) ظرفیتِ وزنی/حجمیِ همهٔ انبارها (تا کنون فقط برایِ خودرو: vehicle_capacity_*).
-- ۳) inv.cycle_count_plans: برنامهٔ شمارشِ دوره‌ای (کالا/گروه/کلاسِ ABC × انبار × تواتر).
-- ۴) inv.warehouse_tasks: وظایفِ جانمایی (Putaway) و برداشت (Picking) -- لایهٔ ثبتِ زمان و اپراتور؛
--    جابه‌جاییِ موجودی فقط با سندِ انتقالِ معمولیِ سیستم انجام می‌شود.
-- بازگشت (rollback):
--   DROP TABLE IF EXISTS inv.warehouse_tasks, inv.cycle_count_plans, inv.cost_adjustment_log;
--   ALTER TABLE inv.warehouses DROP COLUMN IF EXISTS capacity_weight_kg, DROP COLUMN IF EXISTS capacity_volume_m3;
CREATE TABLE IF NOT EXISTS inv.cost_adjustment_log (
    log_id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    adjusted_on DATE NOT NULL DEFAULT CURRENT_DATE,
    adjusted_at TIMESTAMP NOT NULL DEFAULT now(),
    costing_method VARCHAR(20) NULL,
    unit_cost_delta NUMERIC(18, 6) NOT NULL,
    quantity_remaining NUMERIC(18, 6) NOT NULL DEFAULT 0,
    quantity_consumed NUMERIC(18, 6) NOT NULL DEFAULT 0,
    inventory_value_delta NUMERIC(18, 2) NOT NULL DEFAULT 0,
    variance_value_delta NUMERIC(18, 2) NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_inv_cost_adjustment_log_item ON inv.cost_adjustment_log (company_id, item_id, warehouse_id, adjusted_on);

ALTER TABLE inv.warehouses
    ADD COLUMN IF NOT EXISTS capacity_weight_kg NUMERIC(18, 3) NULL,
    ADD COLUMN IF NOT EXISTS capacity_volume_m3 NUMERIC(18, 3) NULL;

CREATE TABLE IF NOT EXISTS inv.cycle_count_plans (
    plan_id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    item_id INT NULL REFERENCES inv.items(item_id),
    category_id INT NULL REFERENCES inv.item_categories(category_id),
    abc_class CHAR(1) NULL CHECK (abc_class IN ('A', 'B', 'C')),
    frequency_days SMALLINT NOT NULL CHECK (frequency_days > 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    notes VARCHAR(500) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_inv_cycle_count_plans UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS inv.warehouse_tasks (
    task_id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    task_type_code VARCHAR(15) NOT NULL CHECK (task_type_code IN ('PUTAWAY', 'PICK')),
    source_stock_document_id BIGINT NULL REFERENCES inv.stock_documents(stock_document_id),
    source_stock_line_id BIGINT NULL REFERENCES inv.stock_document_lines(line_id),
    source_commercial_document_id BIGINT NULL REFERENCES comm.commercial_documents(document_id),
    source_commercial_line_id BIGINT NULL REFERENCES comm.commercial_document_lines(line_id),
    item_id INT NOT NULL REFERENCES inv.items(item_id),
    quantity_base NUMERIC(18, 6) NOT NULL,
    done_quantity_base NUMERIC(18, 6) NULL,
    from_bin_location_id INT NULL REFERENCES inv.bin_locations(bin_location_id),
    to_bin_location_id INT NULL REFERENCES inv.bin_locations(bin_location_id),
    status_code VARCHAR(15) NOT NULL DEFAULT 'OPEN' CHECK (status_code IN ('OPEN', 'IN_PROGRESS', 'DONE', 'CANCELLED')),
    assigned_user_id INT NULL REFERENCES sec.users(user_id),
    created_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    completed_by_user_id INT NULL REFERENCES sec.users(user_id),
    resulting_stock_document_id BIGINT NULL REFERENCES inv.stock_documents(stock_document_id),
    notes VARCHAR(500) NULL
);
CREATE INDEX IF NOT EXISTS ix_inv_warehouse_tasks_status ON inv.warehouse_tasks (company_id, task_type_code, status_code);
CREATE INDEX IF NOT EXISTS ix_inv_warehouse_tasks_stock_line ON inv.warehouse_tasks (source_stock_line_id);
CREATE INDEX IF NOT EXISTS ix_inv_warehouse_tasks_comm_line ON inv.warehouse_tasks (source_commercial_line_id);
