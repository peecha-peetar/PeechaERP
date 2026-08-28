-- پیچا | ماژولِ انبار و لجستیک — انبارگردانی (شمارشِ فیزیکیِ کور)
-- طبقِ سندِ معماری (مرحلهٔ ۹): کاربرگِ شمارش جدولِ اختصاصیِ خودش را دارد
-- (نه overload‌کردنِ stock_document_lینِ عمومی)؛ نتیجهٔ نهاییِ یک جلسهٔ
-- تاییدشده، یک سندِ ADJUSTMENT معمولی است.
-- پیش‌نیاز: 061_inventory_costing_planning_integration.sql

CREATE TABLE inv.cycle_count_sessions (
    session_id                INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                  INT        NOT NULL REFERENCES core.companies(company_id),
    warehouse_id                  INT      NOT NULL REFERENCES inv.warehouses(warehouse_id),
    session_code                    VARCHAR(30) NOT NULL,
    scope_type_code                   VARCHAR(20) NOT NULL
        CHECK (scope_type_code IN ('FULL', 'BY_CATEGORY', 'BY_ITEM', 'BY_BIN', 'ABC_CYCLE')),
    scope_filter                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    status_code                         VARCHAR(20) NOT NULL DEFAULT 'PLANNED'
        CHECK (status_code IN ('PLANNED', 'SNAPSHOT_TAKEN', 'COUNTING', 'RECONCILING', 'APPROVED', 'POSTED', 'CANCELLED')),
    is_blind_count                       BOOLEAN NOT NULL DEFAULT TRUE,
    snapshot_at                           TIMESTAMPTZ NULL,
    approved_by_user_id                     INT NULL REFERENCES sec.users(user_id),
    approved_at                              TIMESTAMPTZ NULL,
    resulting_stock_document_id               BIGINT NULL REFERENCES inv.stock_documents(stock_document_id),
    created_by_user_id                         INT NOT NULL REFERENCES sec.users(user_id),
    created_at                                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_inv_cycle_count_sessions UNIQUE (company_id, session_code)
);

CREATE TABLE inv.cycle_count_lines (
    line_id                     BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id                    INT        NOT NULL REFERENCES inv.cycle_count_sessions(session_id),
    item_id                         INT       NOT NULL REFERENCES inv.items(item_id),
    bin_location_id                   INT     NOT NULL REFERENCES inv.bin_locations(bin_location_id),
    batch_id                           INT    NULL REFERENCES inv.batches(batch_id),
    expected_quantity_base                NUMERIC(18,6) NOT NULL,
    counted_quantity_base                   NUMERIC(18,6) NULL,
    variance_quantity_base                    NUMERIC(18,6) GENERATED ALWAYS AS (counted_quantity_base - expected_quantity_base) STORED,
    counted_by_user_id                         INT NULL REFERENCES sec.users(user_id),
    counted_at                                  TIMESTAMPTZ NULL,
    recount_requested                             BOOLEAN NOT NULL DEFAULT FALSE,
    notes                                          VARCHAR(500) NULL
);
CREATE UNIQUE INDEX ux_inv_cycle_count_lines_no_batch
    ON inv.cycle_count_lines(session_id, item_id, bin_location_id) WHERE batch_id IS NULL;
CREATE UNIQUE INDEX ux_inv_cycle_count_lines_batch
    ON inv.cycle_count_lines(session_id, item_id, bin_location_id, batch_id) WHERE batch_id IS NOT NULL;

-- تکمیلِ FKِ Forward-Reference از 059 (سندِ ADJUSTMENTِ خودکارِ خروجیِ جلسه)
ALTER TABLE inv.stock_documents
    ADD CONSTRAINT fk_inv_stock_documents_cycle_count_session
        FOREIGN KEY (cycle_count_session_id) REFERENCES inv.cycle_count_sessions(session_id);
