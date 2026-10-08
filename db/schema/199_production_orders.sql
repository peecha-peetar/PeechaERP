-- پیچا R267: دستورِ تولید، رزرو، مصرف/برگشت، رسیدِ محصول، ضایعات، WIP -- فقط افزودنی.
-- حرکت‌هایِ موجودی همان اسنادِ انبارِ موجود (ISSUE/RECEIPT) هستند که از موتورِ انبار ثبت می‌شوند؛
-- اینجا فقط اتصالِ آن‌ها به دستورِ تولید (prd.order_transactions.stock_document_id) نگه داشته می‌شود.
CREATE TABLE IF NOT EXISTS prd.production_orders (
    order_id                       BIGSERIAL     PRIMARY KEY,
    company_id                     INT           NOT NULL REFERENCES core.companies(company_id),
    order_no                       INT           NOT NULL,
    order_code                     VARCHAR(30)   NOT NULL,
    item_id                        INT           NOT NULL REFERENCES inv.items(item_id),
    bom_id                         BIGINT        NULL REFERENCES inv.bom_headers(bom_id),
    routing_id                     INT           NULL REFERENCES prd.routings(routing_id),
    parent_order_id                BIGINT        NULL REFERENCES prd.production_orders(order_id),
    planned_qty                    NUMERIC(18,6) NOT NULL CHECK (planned_qty > 0),
    produced_qty                   NUMERIC(18,6) NOT NULL DEFAULT 0,
    scrapped_qty                   NUMERIC(18,6) NOT NULL DEFAULT 0,
    uom_id                         INT           NOT NULL REFERENCES inv.uom(uom_id),
    start_date                     DATE          NOT NULL,
    due_date                       DATE          NOT NULL,
    actual_start_date              DATE          NULL,
    actual_end_date                DATE          NULL,
    material_warehouse_id          INT           NULL REFERENCES inv.warehouses(warehouse_id),
    wip_warehouse_id               INT           NULL REFERENCES inv.warehouses(warehouse_id),
    fg_warehouse_id                INT           NULL REFERENCES inv.warehouses(warehouse_id),
    scrap_warehouse_id             INT           NULL REFERENCES inv.warehouses(warehouse_id),
    branch_id                      INT           NULL REFERENCES comm.branches(branch_id),
    cost_center_detail_account_id  INT           NULL REFERENCES acc.detail_accounts(detail_account_id),
    project_detail_account_id      INT           NULL REFERENCES acc.detail_accounts(detail_account_id),
    work_center_id                 INT           NULL REFERENCES prd.work_centers(work_center_id),
    priority                       SMALLINT      NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    responsible_user_id            INT           NULL REFERENCES sec.users(user_id),
    status_code                    VARCHAR(12)   NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'PLANNED', 'RELEASED', 'IN_PROGRESS', 'ON_HOLD', 'COMPLETED', 'CLOSED', 'CANCELLED')),
    hold_reason                    VARCHAR(300)  NULL,
    sales_order_line_id            BIGINT        NULL REFERENCES comm.commercial_document_lines(line_id),
    joint_cost_method              VARCHAR(20)   NULL,
    standard_unit_cost             NUMERIC(18,6) NULL,
    planned_unit_cost              NUMERIC(18,6) NULL,
    notes                          VARCHAR(1000) NULL,
    idempotency_key                VARCHAR(80)   NULL UNIQUE,
    created_by_user_id             INT           NOT NULL REFERENCES sec.users(user_id),
    created_at                     TIMESTAMP     NOT NULL DEFAULT now(),
    released_at                    TIMESTAMP     NULL,
    completed_at                   TIMESTAMP     NULL,
    closed_at                      TIMESTAMP     NULL,
    closed_by_user_id              INT           NULL REFERENCES sec.users(user_id),
    UNIQUE (company_id, order_no),
    CHECK (due_date >= start_date)
);
CREATE INDEX IF NOT EXISTS ix_prd_orders_status ON prd.production_orders (company_id, status_code);
CREATE INDEX IF NOT EXISTS ix_prd_orders_item ON prd.production_orders (item_id);
CREATE INDEX IF NOT EXISTS ix_prd_orders_dates ON prd.production_orders (company_id, start_date, due_date);

-- موادِ دستور (کپیِ ثابتِ BOM هنگامِ صدور)
CREATE TABLE IF NOT EXISTS prd.order_materials (
    material_id          BIGSERIAL     PRIMARY KEY,
    order_id             BIGINT        NOT NULL REFERENCES prd.production_orders(order_id),
    line_no              INT           NOT NULL,
    item_id              INT           NOT NULL REFERENCES inv.items(item_id),
    bom_line_id          BIGINT        NULL REFERENCES inv.bom_lines(bom_line_id),
    component_type       VARCHAR(15)   NOT NULL DEFAULT 'MATERIAL',
    warehouse_id         INT           NULL REFERENCES inv.warehouses(warehouse_id),
    operation_seq        INT           NULL,
    quantity_type        VARCHAR(10)   NOT NULL DEFAULT 'VARIABLE',
    quantity_per_base    NUMERIC(18,6) NOT NULL,
    batch_size_qty       NUMERIC(18,6) NOT NULL DEFAULT 1,
    scrap_percent        NUMERIC(7,4)  NOT NULL DEFAULT 0,
    planned_qty          NUMERIC(18,6) NOT NULL DEFAULT 0,
    issued_qty           NUMERIC(18,6) NOT NULL DEFAULT 0,
    returned_qty         NUMERIC(18,6) NOT NULL DEFAULT 0,
    reserved_qty         NUMERIC(18,6) NOT NULL DEFAULT 0,
    issued_amount        NUMERIC(18,2) NOT NULL DEFAULT 0,
    returned_amount      NUMERIC(18,2) NOT NULL DEFAULT 0,
    standard_unit_cost   NUMERIC(18,6) NULL,
    is_optional          BOOLEAN       NOT NULL DEFAULT FALSE,
    substitute_item_id   INT           NULL REFERENCES inv.items(item_id),
    UNIQUE (order_id, line_no),
    CHECK (returned_qty <= issued_qty)
);
CREATE INDEX IF NOT EXISTS ix_prd_order_materials_item ON prd.order_materials (item_id);

-- خروجی‌ها: محصولِ اصلی + جانبی + مشترک
CREATE TABLE IF NOT EXISTS prd.order_outputs (
    output_id               BIGSERIAL     PRIMARY KEY,
    order_id                BIGINT        NOT NULL REFERENCES prd.production_orders(order_id),
    item_id                 INT           NOT NULL REFERENCES inv.items(item_id),
    output_type             VARCHAR(12)   NOT NULL CHECK (output_type IN ('MAIN', 'BY_PRODUCT', 'CO_PRODUCT')),
    planned_qty             NUMERIC(18,6) NOT NULL DEFAULT 0,
    produced_qty            NUMERIC(18,6) NOT NULL DEFAULT 0,
    produced_amount         NUMERIC(18,2) NOT NULL DEFAULT 0,
    recovery_value_per_unit NUMERIC(18,6) NULL,
    sales_value_per_unit    NUMERIC(18,6) NULL,
    weight_per_unit         NUMERIC(18,6) NULL,
    cost_share_percent      NUMERIC(7,4)  NULL,
    UNIQUE (order_id, item_id)
);

-- عملیاتِ دستور (کپیِ مسیرِ تولید)
CREATE TABLE IF NOT EXISTS prd.order_operations (
    order_operation_id   BIGSERIAL     PRIMARY KEY,
    order_id             BIGINT        NOT NULL REFERENCES prd.production_orders(order_id),
    seq                  INT           NOT NULL,
    name                 VARCHAR(150)  NOT NULL,
    work_center_id       INT           NULL REFERENCES prd.work_centers(work_center_id),
    asset_id             BIGINT        NULL REFERENCES fa.assets(asset_id),
    labor_rate           NUMERIC(18,2) NOT NULL DEFAULT 0,
    machine_rate         NUMERIC(18,2) NOT NULL DEFAULT 0,
    overhead_rate        NUMERIC(18,2) NOT NULL DEFAULT 0,
    std_labor_hours      NUMERIC(14,4) NOT NULL DEFAULT 0,
    std_machine_hours    NUMERIC(14,4) NOT NULL DEFAULT 0,
    std_elapsed_hours    NUMERIC(14,4) NOT NULL DEFAULT 0,
    status_code          VARCHAR(12)   NOT NULL DEFAULT 'PENDING' CHECK (status_code IN ('PENDING', 'IN_PROGRESS', 'DONE', 'SKIPPED')),
    completed_qty        NUMERIC(18,6) NOT NULL DEFAULT 0,
    actual_labor_hours   NUMERIC(14,4) NOT NULL DEFAULT 0,
    actual_machine_hours NUMERIC(14,4) NOT NULL DEFAULT 0,
    started_at           TIMESTAMP     NULL,
    finished_at          TIMESTAMP     NULL,
    UNIQUE (order_id, seq)
);

-- دفترِ تراکنش‌هایِ دستور (فقط افزودنی؛ اصلاح با ردیفِ برگشتی). WIP = جمعِ wip_delta.
CREATE TABLE IF NOT EXISTS prd.order_transactions (
    txn_id               BIGSERIAL     PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    order_id             BIGINT        NOT NULL REFERENCES prd.production_orders(order_id),
    txn_type             VARCHAR(12)   NOT NULL CHECK (txn_type IN ('ISSUE', 'RETURN', 'RECEIPT', 'BY_PRODUCT', 'CO_PRODUCT',
                                                                     'SCRAP', 'LABOR', 'MACHINE', 'OVERHEAD', 'VARIANCE',
                                                                     'REVERSAL')),
    txn_date             DATE          NOT NULL,
    item_id              INT           NULL REFERENCES inv.items(item_id),
    quantity             NUMERIC(18,6) NOT NULL DEFAULT 0,
    amount               NUMERIC(18,2) NOT NULL DEFAULT 0,
    wip_delta            NUMERIC(18,2) NOT NULL DEFAULT 0,
    material_id          BIGINT        NULL REFERENCES prd.order_materials(material_id),
    output_id            BIGINT        NULL REFERENCES prd.order_outputs(output_id),
    order_operation_id   BIGINT        NULL REFERENCES prd.order_operations(order_operation_id),
    stock_document_id    BIGINT        NULL REFERENCES inv.stock_documents(stock_document_id),
    journal_entry_id     INT           NULL REFERENCES acc.journal_entries(journal_entry_id),
    reason               VARCHAR(300)  NULL,
    details              JSONB         NULL,
    idempotency_key      VARCHAR(80)   NULL UNIQUE,
    reversed_txn_id      BIGINT        NULL REFERENCES prd.order_transactions(txn_id),
    created_by_user_id   INT           NULL REFERENCES sec.users(user_id),
    created_at           TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_prd_txn_order ON prd.order_transactions (order_id, txn_type);
CREATE INDEX IF NOT EXISTS ix_prd_txn_stock_doc ON prd.order_transactions (stock_document_id);
CREATE INDEX IF NOT EXISTS ix_prd_txn_date ON prd.order_transactions (company_id, txn_date);
CREATE UNIQUE INDEX IF NOT EXISTS ux_prd_txn_reversed ON prd.order_transactions (reversed_txn_id) WHERE reversed_txn_id IS NOT NULL;

CREATE OR REPLACE FUNCTION prd.fn_order_txn_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'تراکنشِ دستورِ تولید قابلِ ویرایش/حذف نیست؛ برایِ اصلاح ردیفِ برگشتی ثبت کنید.';
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS tr_prd_order_txn_immutable ON prd.order_transactions;
CREATE TRIGGER tr_prd_order_txn_immutable BEFORE UPDATE OR DELETE ON prd.order_transactions
    FOR EACH ROW EXECUTE FUNCTION prd.fn_order_txn_immutable();
