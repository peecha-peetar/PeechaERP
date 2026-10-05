-- پیچا R268: هزینه‌یابیِ تولید -- دستمزد، ماشین، سربار و موتورِ سرشکن، بهایِ استاندارد/واقعی، انحراف، بستنِ دوره. فقط افزودنی.
CREATE TABLE IF NOT EXISTS prd.labor_entries (
    entry_id                       BIGSERIAL     PRIMARY KEY,
    company_id                     INT           NOT NULL REFERENCES core.companies(company_id),
    order_id                       BIGINT        NOT NULL REFERENCES prd.production_orders(order_id),
    order_operation_id             BIGINT        NULL REFERENCES prd.order_operations(order_operation_id),
    employee_id                    INT           NULL REFERENCES hr.employees(employee_id),
    work_center_id                 INT           NULL REFERENCES prd.work_centers(work_center_id),
    work_date                      DATE          NOT NULL,
    hours                          NUMERIC(14,4) NOT NULL DEFAULT 0 CHECK (hours >= 0),
    overtime_hours                 NUMERIC(14,4) NOT NULL DEFAULT 0 CHECK (overtime_hours >= 0),
    rate                           NUMERIC(18,2) NOT NULL CHECK (rate >= 0),
    overtime_rate                  NUMERIC(18,2) NOT NULL DEFAULT 0,
    amount                         NUMERIC(18,2) NOT NULL,
    cost_center_detail_account_id  INT           NULL REFERENCES acc.detail_accounts(detail_account_id),
    is_standard                    BOOLEAN       NOT NULL DEFAULT FALSE,
    txn_id                         BIGINT        NULL REFERENCES prd.order_transactions(txn_id),
    notes                          VARCHAR(300)  NULL,
    created_by_user_id             INT           NULL REFERENCES sec.users(user_id),
    created_at                     TIMESTAMP     NOT NULL DEFAULT now(),
    CHECK (hours + overtime_hours > 0)
);
CREATE INDEX IF NOT EXISTS ix_prd_labor_order ON prd.labor_entries (order_id);
CREATE INDEX IF NOT EXISTS ix_prd_labor_date ON prd.labor_entries (company_id, work_date);

CREATE TABLE IF NOT EXISTS prd.machine_entries (
    entry_id             BIGSERIAL     PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    order_id             BIGINT        NOT NULL REFERENCES prd.production_orders(order_id),
    order_operation_id   BIGINT        NULL REFERENCES prd.order_operations(order_operation_id),
    work_center_id       INT           NULL REFERENCES prd.work_centers(work_center_id),
    asset_id             BIGINT        NULL REFERENCES fa.assets(asset_id),
    work_date            DATE          NOT NULL,
    hours                NUMERIC(14,4) NOT NULL CHECK (hours > 0),
    rate                 NUMERIC(18,6) NOT NULL CHECK (rate >= 0),
    amount               NUMERIC(18,2) NOT NULL,
    is_standard          BOOLEAN       NOT NULL DEFAULT FALSE,
    fa_allocation_id     BIGINT        NULL REFERENCES fa.machine_cost_allocations(allocation_id),
    txn_id               BIGINT        NULL REFERENCES prd.order_transactions(txn_id),
    created_by_user_id   INT           NULL REFERENCES sec.users(user_id),
    created_at           TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_prd_machine_order ON prd.machine_entries (order_id);

-- استخرِ هزینه (سربارِ کارخانه، برق، اجاره، ...) و قاعدهٔ سرشکن
CREATE TABLE IF NOT EXISTS prd.cost_pools (
    pool_id            SERIAL        PRIMARY KEY,
    company_id         INT           NOT NULL REFERENCES core.companies(company_id),
    code               VARCHAR(30)   NOT NULL,
    name               VARCHAR(150)  NOT NULL,
    category           VARCHAR(20)   NOT NULL DEFAULT 'OVERHEAD'
        CHECK (category IN ('ELECTRICITY', 'GAS', 'DEPRECIATION', 'MAINTENANCE', 'RENT', 'INSURANCE', 'INDIRECT', 'OVERHEAD', 'OTHER')),
    period_code        VARCHAR(7)    NOT NULL,
    amount             NUMERIC(18,2) NOT NULL CHECK (amount >= 0),
    basis              VARCHAR(20)   NOT NULL
        CHECK (basis IN ('LABOR_HOURS', 'MACHINE_HOURS', 'QUANTITY', 'MATERIAL_COST', 'LABOR_COST', 'PERCENTAGE', 'MANUAL')),
    work_center_id     INT           NULL REFERENCES prd.work_centers(work_center_id),
    allocated_amount   NUMERIC(18,2) NOT NULL DEFAULT 0,
    status_code        VARCHAR(10)   NOT NULL DEFAULT 'OPEN' CHECK (status_code IN ('OPEN', 'ALLOCATED')),
    notes              VARCHAR(300)  NULL,
    created_at         TIMESTAMP     NOT NULL DEFAULT now(),
    UNIQUE (company_id, code, period_code)
);

CREATE TABLE IF NOT EXISTS prd.cost_allocations (
    allocation_id   BIGSERIAL     PRIMARY KEY,
    pool_id         INT           NOT NULL REFERENCES prd.cost_pools(pool_id),
    order_id        BIGINT        NOT NULL REFERENCES prd.production_orders(order_id),
    basis_value     NUMERIC(18,4) NOT NULL DEFAULT 0,
    amount          NUMERIC(18,2) NOT NULL,
    txn_id          BIGINT        NULL REFERENCES prd.order_transactions(txn_id),
    created_at      TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_prd_cost_alloc_pool ON prd.cost_allocations (pool_id);

-- کارتِ بهایِ استاندارد (چندسطحی) -- جمعِ آن در همان inv.standard_costs نوشته می‌شود
CREATE TABLE IF NOT EXISTS prd.standard_cost_cards (
    card_id          BIGSERIAL     PRIMARY KEY,
    company_id       INT           NOT NULL REFERENCES core.companies(company_id),
    item_id          INT           NOT NULL REFERENCES inv.items(item_id),
    effective_date   DATE          NOT NULL,
    bom_id           BIGINT        NULL REFERENCES inv.bom_headers(bom_id),
    routing_id       INT           NULL REFERENCES prd.routings(routing_id),
    material_cost    NUMERIC(18,6) NOT NULL DEFAULT 0,
    labor_cost       NUMERIC(18,6) NOT NULL DEFAULT 0,
    machine_cost     NUMERIC(18,6) NOT NULL DEFAULT 0,
    overhead_cost    NUMERIC(18,6) NOT NULL DEFAULT 0,
    byproduct_credit NUMERIC(18,6) NOT NULL DEFAULT 0,
    total_cost       NUMERIC(18,6) NOT NULL DEFAULT 0,
    details          JSONB         NULL,
    created_by_user_id INT         NULL REFERENCES sec.users(user_id),
    created_at       TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_prd_std_cards_item ON prd.standard_cost_cards (item_id, effective_date);

-- خلاصهٔ بها و انحراف‌هایِ هر دستور (در بستن نوشته می‌شود)
CREATE TABLE IF NOT EXISTS prd.order_cost_summaries (
    order_id          BIGINT        PRIMARY KEY REFERENCES prd.production_orders(order_id),
    computed_at       TIMESTAMP     NOT NULL DEFAULT now(),
    produced_qty      NUMERIC(18,6) NOT NULL DEFAULT 0,
    material_std      NUMERIC(18,2) NOT NULL DEFAULT 0,
    material_actual   NUMERIC(18,2) NOT NULL DEFAULT 0,
    labor_std         NUMERIC(18,2) NOT NULL DEFAULT 0,
    labor_actual      NUMERIC(18,2) NOT NULL DEFAULT 0,
    machine_std       NUMERIC(18,2) NOT NULL DEFAULT 0,
    machine_actual    NUMERIC(18,2) NOT NULL DEFAULT 0,
    overhead_std      NUMERIC(18,2) NOT NULL DEFAULT 0,
    overhead_actual   NUMERIC(18,2) NOT NULL DEFAULT 0,
    byproduct_credit  NUMERIC(18,2) NOT NULL DEFAULT 0,
    scrap_recovery    NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_std         NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_actual      NUMERIC(18,2) NOT NULL DEFAULT 0,
    std_unit_cost     NUMERIC(18,6) NOT NULL DEFAULT 0,
    actual_unit_cost  NUMERIC(18,6) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS prd.order_variances (
    variance_id     BIGSERIAL     PRIMARY KEY,
    order_id        BIGINT        NOT NULL REFERENCES prd.production_orders(order_id),
    variance_code   VARCHAR(30)   NOT NULL,
    amount          NUMERIC(18,2) NOT NULL DEFAULT 0,
    quantity        NUMERIC(18,6) NULL,
    details         JSONB         NULL,
    UNIQUE (order_id, variance_code)
);

-- بستنِ دوره‌ایِ بها
CREATE TABLE IF NOT EXISTS prd.cost_closings (
    closing_id           SERIAL        PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    period_code          VARCHAR(7)    NOT NULL,
    period_start         DATE          NOT NULL,
    period_end           DATE          NOT NULL,
    status_code          VARCHAR(10)   NOT NULL DEFAULT 'FINALIZED' CHECK (status_code IN ('FINALIZED', 'REOPENED')),
    orders_count         INT           NOT NULL DEFAULT 0,
    wip_balance          NUMERIC(18,2) NOT NULL DEFAULT 0,
    material_total       NUMERIC(18,2) NOT NULL DEFAULT 0,
    labor_total          NUMERIC(18,2) NOT NULL DEFAULT 0,
    machine_total        NUMERIC(18,2) NOT NULL DEFAULT 0,
    overhead_applied     NUMERIC(18,2) NOT NULL DEFAULT 0,
    overhead_pools       NUMERIC(18,2) NOT NULL DEFAULT 0,
    output_total         NUMERIC(18,2) NOT NULL DEFAULT 0,
    variance_total       NUMERIC(18,2) NOT NULL DEFAULT 0,
    details              JSONB         NULL,
    finalized_by_user_id INT           NULL REFERENCES sec.users(user_id),
    finalized_at         TIMESTAMP     NOT NULL DEFAULT now(),
    reopened_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    reopened_at          TIMESTAMP     NULL,
    reopen_reason        VARCHAR(300)  NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_prd_cost_closing_period ON prd.cost_closings (company_id, period_code) WHERE status_code = 'FINALIZED';
