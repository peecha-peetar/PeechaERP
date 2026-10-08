-- پیچا R266: ماژولِ تولید -- فاز ۱ (اطلاعاتِ پایه). فقط افزودنی؛ هیچ جدول/ستونِ قبلی حذف یا تغییرِ نام نمی‌شود.
-- BOMِ موجود (inv.bom_headers/bom_lines) با ستون‌هایِ تازه کامل می‌شود؛ BOMِ موازی ساخته نمی‌شود.
CREATE SCHEMA IF NOT EXISTS prd;

-- تنظیماتِ تولیدِ شرکت
CREATE TABLE IF NOT EXISTS prd.production_settings (
    company_id                        INT          PRIMARY KEY REFERENCES core.companies(company_id),
    default_material_warehouse_id     INT          NULL REFERENCES inv.warehouses(warehouse_id),
    default_production_warehouse_id   INT          NULL REFERENCES inv.warehouses(warehouse_id),
    default_fg_warehouse_id           INT          NULL REFERENCES inv.warehouses(warehouse_id),
    default_scrap_warehouse_id        INT          NULL REFERENCES inv.warehouses(warehouse_id),
    default_cost_center_detail_account_id INT      NULL REFERENCES acc.detail_accounts(detail_account_id),
    auto_reservation                  BOOLEAN      NOT NULL DEFAULT TRUE,
    auto_consumption                  BOOLEAN      NOT NULL DEFAULT FALSE,
    allow_over_consumption            BOOLEAN      NOT NULL DEFAULT TRUE,
    allow_under_consumption           BOOLEAN      NOT NULL DEFAULT TRUE,
    auto_cost_calculation             BOOLEAN      NOT NULL DEFAULT TRUE,
    require_cost_closing              BOOLEAN      NOT NULL DEFAULT FALSE,
    allow_negative_material           BOOLEAN      NOT NULL DEFAULT FALSE,
    shortage_policy                   VARCHAR(10)  NOT NULL DEFAULT 'WARN' CHECK (shortage_policy IN ('WARN', 'BLOCK')),
    require_cost_center               BOOLEAN      NOT NULL DEFAULT FALSE,
    default_overhead_basis            VARCHAR(20)  NOT NULL DEFAULT 'LABOR_HOURS'
        CHECK (default_overhead_basis IN ('LABOR_HOURS', 'MACHINE_HOURS', 'QUANTITY', 'MATERIAL_COST', 'LABOR_COST',
                                          'PERCENTAGE', 'MANUAL')),
    default_joint_cost_method         VARCHAR(20)  NOT NULL DEFAULT 'QUANTITY'
        CHECK (default_joint_cost_method IN ('QUANTITY', 'WEIGHT', 'SALES_VALUE', 'NRV', 'PERCENTAGE', 'MANUAL')),
    abnormal_scrap_percent            NUMERIC(7,4) NOT NULL DEFAULT 5 CHECK (abnormal_scrap_percent >= 0),
    order_prefix                      VARCHAR(10)  NOT NULL DEFAULT 'PO',
    updated_at                        TIMESTAMP    NOT NULL DEFAULT now()
);

-- مشخصاتِ تولیدیِ کالا (واحدِ تولید/مصرف، حداقل/حداکثرِ تولید، زمانِ تأمین، ضایعاتِ استاندارد)
CREATE TABLE IF NOT EXISTS prd.item_production_profiles (
    item_id                 INT           PRIMARY KEY REFERENCES inv.items(item_id),
    company_id              INT           NOT NULL REFERENCES core.companies(company_id),
    make_or_buy             VARCHAR(4)    NOT NULL DEFAULT 'MAKE' CHECK (make_or_buy IN ('MAKE', 'BUY')),
    production_uom_id       INT           NULL REFERENCES inv.uom(uom_id),
    consumption_uom_id      INT           NULL REFERENCES inv.uom(uom_id),
    min_lot_qty             NUMERIC(18,6) NULL CHECK (min_lot_qty IS NULL OR min_lot_qty > 0),
    max_lot_qty             NUMERIC(18,6) NULL CHECK (max_lot_qty IS NULL OR max_lot_qty > 0),
    lot_multiple_qty        NUMERIC(18,6) NULL CHECK (lot_multiple_qty IS NULL OR lot_multiple_qty > 0),
    lead_time_days          INT           NOT NULL DEFAULT 0 CHECK (lead_time_days >= 0),
    standard_scrap_percent  NUMERIC(7,4)  NOT NULL DEFAULT 0 CHECK (standard_scrap_percent BETWEEN 0 AND 100),
    weight_per_unit         NUMERIC(18,6) NULL,
    backflush               BOOLEAN       NULL,
    CHECK (max_lot_qty IS NULL OR min_lot_qty IS NULL OR max_lot_qty >= min_lot_qty)
);

-- مرکزِ کاری (خطِ تولید، مونتاژ، رنگ، بسته‌بندی، ...)
CREATE TABLE IF NOT EXISTS prd.work_centers (
    work_center_id          SERIAL        PRIMARY KEY,
    company_id              INT           NOT NULL REFERENCES core.companies(company_id),
    code                    VARCHAR(30)   NOT NULL,
    name                    VARCHAR(150)  NOT NULL,
    center_type             VARCHAR(15)   NOT NULL DEFAULT 'LINE'
        CHECK (center_type IN ('LINE', 'ASSEMBLY', 'MACHINING', 'PAINT', 'QC', 'PACKING', 'OTHER')),
    branch_id               INT           NULL REFERENCES comm.branches(branch_id),
    warehouse_id            INT           NULL REFERENCES inv.warehouses(warehouse_id),
    cost_center_detail_account_id INT     NULL REFERENCES acc.detail_accounts(detail_account_id),
    operator_count          INT           NOT NULL DEFAULT 1 CHECK (operator_count >= 0),
    shifts_per_day          INT           NOT NULL DEFAULT 1 CHECK (shifts_per_day BETWEEN 0 AND 4),
    hours_per_shift         NUMERIC(6,2)  NOT NULL DEFAULT 8 CHECK (hours_per_shift >= 0),
    working_days_per_week   INT           NOT NULL DEFAULT 6 CHECK (working_days_per_week BETWEEN 0 AND 7),
    hourly_capacity_qty     NUMERIC(18,6) NULL CHECK (hourly_capacity_qty IS NULL OR hourly_capacity_qty >= 0),
    efficiency_percent      NUMERIC(7,4)  NOT NULL DEFAULT 100 CHECK (efficiency_percent > 0),
    labor_rate              NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (labor_rate >= 0),
    machine_rate            NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (machine_rate >= 0),
    overhead_rate           NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (overhead_rate >= 0),
    is_active               BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, code)
);

-- ماشین‌هایِ مرکزِ کاری = داراییِ ثابتِ «ماشینِ تولیدی» (ماژولِ دارایی‌ها)؛ ماشینِ موازی ساخته نمی‌شود
CREATE TABLE IF NOT EXISTS prd.work_center_machines (
    work_center_id  INT     NOT NULL REFERENCES prd.work_centers(work_center_id),
    asset_id        BIGINT  NOT NULL REFERENCES fa.assets(asset_id),
    PRIMARY KEY (work_center_id, asset_id)
);

-- نرخِ دستمزد (گروهِ کاری یا کارمند)
CREATE TABLE IF NOT EXISTS prd.labor_rates (
    labor_rate_id       SERIAL        PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    code                VARCHAR(30)   NOT NULL,
    name                VARCHAR(150)  NOT NULL,
    employee_id         INT           NULL REFERENCES hr.employees(employee_id),
    hourly_rate         NUMERIC(18,2) NOT NULL CHECK (hourly_rate >= 0),
    overtime_multiplier NUMERIC(6,3)  NOT NULL DEFAULT 1.4 CHECK (overtime_multiplier >= 1),
    is_active           BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, code)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_prd_labor_rates_employee ON prd.labor_rates (company_id, employee_id) WHERE employee_id IS NOT NULL;

-- عملیاتِ استاندارد (برش، مونتاژ، رنگ، ...)
CREATE TABLE IF NOT EXISTS prd.operations (
    operation_id           SERIAL        PRIMARY KEY,
    company_id             INT           NOT NULL REFERENCES core.companies(company_id),
    code                   VARCHAR(30)   NOT NULL,
    name                   VARCHAR(150)  NOT NULL,
    default_work_center_id INT           NULL REFERENCES prd.work_centers(work_center_id),
    default_setup_minutes  NUMERIC(10,2) NOT NULL DEFAULT 0,
    default_run_minutes    NUMERIC(12,4) NOT NULL DEFAULT 0,
    is_qc                  BOOLEAN       NOT NULL DEFAULT FALSE,
    is_active              BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, code)
);

-- مسیرِ تولید (نسخه‌دار)
CREATE TABLE IF NOT EXISTS prd.routings (
    routing_id     SERIAL        PRIMARY KEY,
    company_id     INT           NOT NULL REFERENCES core.companies(company_id),
    item_id        INT           NOT NULL REFERENCES inv.items(item_id),
    version_no     INT           NOT NULL DEFAULT 1,
    name           VARCHAR(150)  NULL,
    status_code    VARCHAR(10)   NOT NULL DEFAULT 'ACTIVE' CHECK (status_code IN ('DRAFT', 'ACTIVE', 'ARCHIVED')),
    is_default     BOOLEAN       NOT NULL DEFAULT FALSE,
    valid_from     DATE          NULL,
    valid_to       DATE          NULL,
    created_at     TIMESTAMP     NOT NULL DEFAULT now(),
    UNIQUE (item_id, version_no),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_prd_routings_default ON prd.routings (item_id) WHERE is_default;

CREATE TABLE IF NOT EXISTS prd.routing_operations (
    routing_operation_id  SERIAL        PRIMARY KEY,
    routing_id            INT           NOT NULL REFERENCES prd.routings(routing_id),
    seq                   INT           NOT NULL CHECK (seq > 0),
    operation_id          INT           NULL REFERENCES prd.operations(operation_id),
    name                  VARCHAR(150)  NOT NULL,
    work_center_id        INT           NULL REFERENCES prd.work_centers(work_center_id),
    asset_id              BIGINT        NULL REFERENCES fa.assets(asset_id),
    labor_count           NUMERIC(6,2)  NOT NULL DEFAULT 1 CHECK (labor_count >= 0),
    setup_minutes         NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (setup_minutes >= 0),
    run_minutes           NUMERIC(12,4) NOT NULL DEFAULT 0 CHECK (run_minutes >= 0),
    queue_minutes         NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (queue_minutes >= 0),
    move_minutes          NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (move_minutes >= 0),
    machine_minutes       NUMERIC(12,4) NULL CHECK (machine_minutes IS NULL OR machine_minutes >= 0),
    labor_rate            NUMERIC(18,2) NULL,
    machine_rate          NUMERIC(18,2) NULL,
    overhead_rate         NUMERIC(18,2) NULL,
    scrap_percent         NUMERIC(7,4)  NOT NULL DEFAULT 0 CHECK (scrap_percent BETWEEN 0 AND 100),
    is_qc                 BOOLEAN       NOT NULL DEFAULT FALSE,
    description           VARCHAR(500)  NULL,
    UNIQUE (routing_id, seq)
);

-- تکمیلِ BOMِ موجود
ALTER TABLE inv.bom_headers ADD COLUMN IF NOT EXISTS name VARCHAR(150) NULL;
ALTER TABLE inv.bom_headers ADD COLUMN IF NOT EXISTS status_code VARCHAR(10) NOT NULL DEFAULT 'ACTIVE';
ALTER TABLE inv.bom_headers ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE inv.bom_headers ADD COLUMN IF NOT EXISTS valid_from DATE NULL;
ALTER TABLE inv.bom_headers ADD COLUMN IF NOT EXISTS valid_to DATE NULL;
ALTER TABLE inv.bom_headers ADD COLUMN IF NOT EXISTS routing_id INT NULL REFERENCES prd.routings(routing_id);
ALTER TABLE inv.bom_headers ADD COLUMN IF NOT EXISTS notes VARCHAR(500) NULL;
ALTER TABLE inv.bom_headers ADD COLUMN IF NOT EXISTS is_locked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE inv.bom_headers ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NULL DEFAULT now();
DO $$ BEGIN
    ALTER TABLE inv.bom_headers ADD CONSTRAINT ck_inv_bom_headers_status CHECK (status_code IN ('DRAFT', 'ACTIVE', 'ARCHIVED'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE UNIQUE INDEX IF NOT EXISTS ux_inv_bom_headers_default ON inv.bom_headers (finished_item_id) WHERE is_default;

ALTER TABLE inv.bom_lines ADD COLUMN IF NOT EXISTS uom_id INT NULL REFERENCES inv.uom(uom_id);
ALTER TABLE inv.bom_lines ADD COLUMN IF NOT EXISTS conversion_factor NUMERIC(18,6) NOT NULL DEFAULT 1;
ALTER TABLE inv.bom_lines ADD COLUMN IF NOT EXISTS quantity_type VARCHAR(10) NOT NULL DEFAULT 'VARIABLE';
ALTER TABLE inv.bom_lines ADD COLUMN IF NOT EXISTS component_type VARCHAR(15) NOT NULL DEFAULT 'MATERIAL';
ALTER TABLE inv.bom_lines ADD COLUMN IF NOT EXISTS warehouse_id INT NULL REFERENCES inv.warehouses(warehouse_id);
ALTER TABLE inv.bom_lines ADD COLUMN IF NOT EXISTS operation_seq INT NULL;
ALTER TABLE inv.bom_lines ADD COLUMN IF NOT EXISTS substitute_item_id INT NULL REFERENCES inv.items(item_id);
ALTER TABLE inv.bom_lines ADD COLUMN IF NOT EXISTS is_optional BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE inv.bom_lines ADD COLUMN IF NOT EXISTS notes VARCHAR(300) NULL;
DO $$ BEGIN
    ALTER TABLE inv.bom_lines ADD CONSTRAINT ck_inv_bom_lines_qty_type CHECK (quantity_type IN ('VARIABLE', 'FIXED'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    ALTER TABLE inv.bom_lines ADD CONSTRAINT ck_inv_bom_lines_component_type
        CHECK (component_type IN ('MATERIAL', 'PACKAGING', 'PART', 'SEMI_FINISHED', 'CONSUMABLE'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    ALTER TABLE inv.bom_lines ADD CONSTRAINT ck_inv_bom_lines_conversion CHECK (conversion_factor > 0);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- خروجی‌هایِ جانبی/مشترکِ BOM (محصولِ اصلی همان finished_item_id است)
CREATE TABLE IF NOT EXISTS prd.bom_outputs (
    bom_output_id           SERIAL        PRIMARY KEY,
    bom_id                  BIGINT        NOT NULL REFERENCES inv.bom_headers(bom_id),
    item_id                 INT           NOT NULL REFERENCES inv.items(item_id),
    output_type             VARCHAR(12)   NOT NULL CHECK (output_type IN ('BY_PRODUCT', 'CO_PRODUCT')),
    quantity_per            NUMERIC(18,6) NOT NULL CHECK (quantity_per > 0),
    recovery_value_per_unit NUMERIC(18,6) NULL CHECK (recovery_value_per_unit IS NULL OR recovery_value_per_unit >= 0),
    sales_value_per_unit    NUMERIC(18,6) NULL CHECK (sales_value_per_unit IS NULL OR sales_value_per_unit >= 0),
    weight_per_unit         NUMERIC(18,6) NULL,
    cost_share_percent      NUMERIC(7,4)  NULL CHECK (cost_share_percent IS NULL OR cost_share_percent BETWEEN 0 AND 100),
    UNIQUE (bom_id, item_id)
);

-- نوعِ سندِ حسابداریِ «تولید»
INSERT INTO acc.journal_entry_types (entry_type_id, code) VALUES (12, 'PRODUCTION') ON CONFLICT (entry_type_id) DO NOTHING;
