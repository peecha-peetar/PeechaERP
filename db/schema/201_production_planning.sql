-- پیچا R269: برنامه‌ریزیِ تولید، MRPِ سبک، ظرفیت و تقویمِ تولید -- فقط افزودنی.
CREATE TABLE IF NOT EXISTS prd.production_plans (
    plan_id             SERIAL        PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    code                VARCHAR(30)   NOT NULL,
    name                VARCHAR(150)  NOT NULL,
    period_type         VARCHAR(5)    NOT NULL DEFAULT 'MONTH' CHECK (period_type IN ('DAY', 'WEEK', 'MONTH')),
    start_date          DATE          NOT NULL,
    end_date            DATE          NOT NULL,
    status_code         VARCHAR(10)   NOT NULL DEFAULT 'DRAFT' CHECK (status_code IN ('DRAFT', 'APPROVED', 'CLOSED')),
    notes               VARCHAR(500)  NULL,
    created_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    created_at          TIMESTAMP     NOT NULL DEFAULT now(),
    UNIQUE (company_id, code),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS prd.production_plan_lines (
    line_id              BIGSERIAL     PRIMARY KEY,
    plan_id              INT           NOT NULL REFERENCES prd.production_plans(plan_id),
    item_id              INT           NOT NULL REFERENCES inv.items(item_id),
    planned_date         DATE          NOT NULL,
    quantity             NUMERIC(18,6) NOT NULL CHECK (quantity > 0),
    work_center_id       INT           NULL REFERENCES prd.work_centers(work_center_id),
    source_type          VARCHAR(12)   NOT NULL DEFAULT 'MANUAL' CHECK (source_type IN ('MANUAL', 'SALES_ORDER', 'MIN_STOCK', 'MRP')),
    sales_order_line_id  BIGINT        NULL REFERENCES comm.commercial_document_lines(line_id),
    order_id             BIGINT        NULL REFERENCES prd.production_orders(order_id),
    notes                VARCHAR(300)  NULL
);
CREATE INDEX IF NOT EXISTS ix_prd_plan_lines_plan ON prd.production_plan_lines (plan_id);
CREATE INDEX IF NOT EXISTS ix_prd_plan_lines_date ON prd.production_plan_lines (planned_date);

ALTER TABLE prd.production_orders ADD COLUMN IF NOT EXISTS plan_line_id BIGINT NULL REFERENCES prd.production_plan_lines(line_id);

CREATE TABLE IF NOT EXISTS prd.mrp_runs (
    run_id              SERIAL        PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    run_at              TIMESTAMP     NOT NULL DEFAULT now(),
    horizon_date        DATE          NOT NULL,
    params              JSONB         NULL,
    lines_count         INT           NOT NULL DEFAULT 0,
    created_by_user_id  INT           NULL REFERENCES sec.users(user_id)
);

CREATE TABLE IF NOT EXISTS prd.mrp_lines (
    mrp_line_id          BIGSERIAL     PRIMARY KEY,
    run_id               INT           NOT NULL REFERENCES prd.mrp_runs(run_id),
    item_id              INT           NOT NULL REFERENCES inv.items(item_id),
    level                INT           NOT NULL DEFAULT 0,
    make_or_buy          VARCHAR(4)    NOT NULL,
    gross_requirement    NUMERIC(18,6) NOT NULL DEFAULT 0,
    independent_demand   NUMERIC(18,6) NOT NULL DEFAULT 0,
    dependent_demand     NUMERIC(18,6) NOT NULL DEFAULT 0,
    on_hand              NUMERIC(18,6) NOT NULL DEFAULT 0,
    reserved             NUMERIC(18,6) NOT NULL DEFAULT 0,
    available            NUMERIC(18,6) NOT NULL DEFAULT 0,
    scheduled_receipts   NUMERIC(18,6) NOT NULL DEFAULT 0,
    min_stock            NUMERIC(18,6) NOT NULL DEFAULT 0,
    net_requirement      NUMERIC(18,6) NOT NULL DEFAULT 0,
    suggested_action     VARCHAR(10)   NOT NULL DEFAULT 'NONE' CHECK (suggested_action IN ('PURCHASE', 'PRODUCE', 'NONE')),
    suggested_qty        NUMERIC(18,6) NOT NULL DEFAULT 0,
    need_date            DATE          NULL,
    release_date         DATE          NULL,
    converted_ref        VARCHAR(60)   NULL,
    details              JSONB         NULL
);
CREATE INDEX IF NOT EXISTS ix_prd_mrp_lines_run ON prd.mrp_lines (run_id);
