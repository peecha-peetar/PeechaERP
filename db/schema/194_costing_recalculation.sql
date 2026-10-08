-- پیچا R260: بازمحاسبهٔ بهایِ تمام‌شده -- فقط افزودنی. دفترِ انبار دست نمی‌خورد؛ اصلاح با سندِ حسابداری + لاگِ تاریخ‌دار.
CREATE TABLE IF NOT EXISTS inv.cost_recalculation_runs (
    run_id               BIGSERIAL PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    item_id              INT           NULL REFERENCES inv.items(item_id),
    warehouse_id         INT           NULL REFERENCES inv.warehouses(warehouse_id),
    date_from            DATE          NOT NULL,
    posting_date         DATE          NOT NULL,
    reason               VARCHAR(300)  NULL,
    items_count          INT           NOT NULL DEFAULT 0,
    lines_count          INT           NOT NULL DEFAULT 0,
    total_delta          NUMERIC(18,2) NOT NULL DEFAULT 0,
    journal_entry_id     INT           NULL REFERENCES acc.journal_entries(journal_entry_id),
    created_by_user_id   INT           NULL REFERENCES sec.users(user_id),
    created_at           TIMESTAMP     NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_inv_cost_recalc_runs_company ON inv.cost_recalculation_runs (company_id, created_at DESC);

-- هر ردیفِ سندِ انبار که بهایش عوض شد: مبلغِ قبلی/جدید (سابقهٔ کامل؛ تخصیص‌ها و لایه‌ها به مقدارِ جدید به‌روز می‌شوند)
CREATE TABLE IF NOT EXISTS inv.cost_recalculation_lines (
    recalc_line_id          BIGSERIAL PRIMARY KEY,
    run_id                  BIGINT        NOT NULL REFERENCES inv.cost_recalculation_runs(run_id),
    stock_document_line_id  BIGINT        NOT NULL REFERENCES inv.stock_document_lines(line_id),
    item_id                 INT           NOT NULL REFERENCES inv.items(item_id),
    warehouse_id            INT           NOT NULL REFERENCES inv.warehouses(warehouse_id),
    bin_location_id         INT           NULL REFERENCES inv.bin_locations(bin_location_id),
    movement_direction      VARCHAR(3)    NOT NULL CHECK (movement_direction IN ('IN', 'OUT')),
    costing_method_code     VARCHAR(20)   NOT NULL,
    quantity_base           NUMERIC(18,6) NOT NULL,
    old_amount              NUMERIC(18,2) NOT NULL,
    new_amount              NUMERIC(18,2) NOT NULL,
    delta_amount            NUMERIC(18,2) GENERATED ALWAYS AS (new_amount - old_amount) STORED
);
CREATE INDEX IF NOT EXISTS ix_inv_cost_recalc_lines_line ON inv.cost_recalculation_lines (stock_document_line_id);
CREATE INDEX IF NOT EXISTS ix_inv_cost_recalc_lines_run ON inv.cost_recalculation_lines (run_id);
