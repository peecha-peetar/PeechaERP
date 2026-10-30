-- پیچا | R372: تغییر مهندسی محصول (ECO) — درخواست تغییر روی یک نسخهٔ فهرست مواد با ردیف‌های افزودن، تغییر، جایگزینی و حذف جزء،
-- تایید و اجرا با ساخت نسخهٔ جدید فهرست مواد از تاریخ اجرا
CREATE TABLE IF NOT EXISTS prd.eco_orders (
    eco_id                  INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id              INT           NOT NULL REFERENCES core.companies(company_id),
    eco_no                  INT           NOT NULL,
    title                   VARCHAR(200)  NOT NULL,
    item_id                 INT           NOT NULL REFERENCES inv.items(item_id),
    base_bom_id             BIGINT        NOT NULL REFERENCES inv.bom_headers(bom_id),
    new_bom_id              BIGINT        REFERENCES inv.bom_headers(bom_id),
    reason_code             VARCHAR(20)   NOT NULL DEFAULT 'DESIGN'
        CHECK (reason_code IN ('DESIGN', 'COST', 'QUALITY', 'SUPPLY', 'CUSTOMER', 'REGULATION', 'OTHER')),
    description             VARCHAR(1000),
    effective_date          DATE          NOT NULL,
    stock_disposition       VARCHAR(10)   NOT NULL DEFAULT 'USE_UP' CHECK (stock_disposition IN ('USE_UP', 'REWORK', 'SCRAP')),
    status_code             VARCHAR(12)   NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'IMPLEMENTED', 'CANCELLED')),
    requested_by_user_id    INT           REFERENCES sec.users(user_id),
    decided_by_user_id      INT           REFERENCES sec.users(user_id),
    decided_at              TIMESTAMPTZ,
    decision_note           VARCHAR(500),
    implemented_by_user_id  INT           REFERENCES sec.users(user_id),
    implemented_at          TIMESTAMPTZ,
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT uq_prd_eco_orders_no UNIQUE (company_id, eco_no)
);

CREATE TABLE IF NOT EXISTS prd.eco_lines (
    eco_line_id        INT            GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    eco_id             INT            NOT NULL REFERENCES prd.eco_orders(eco_id) ON DELETE CASCADE,
    line_no            SMALLINT       NOT NULL,
    action_code        VARCHAR(10)    NOT NULL CHECK (action_code IN ('ADD', 'CHANGE', 'REPLACE', 'REMOVE')),
    base_line_no       SMALLINT,
    component_item_id  INT            NOT NULL REFERENCES inv.items(item_id),
    new_item_id        INT            REFERENCES inv.items(item_id),
    old_quantity       NUMERIC(18,6),
    new_quantity       NUMERIC(18,6)  CHECK (new_quantity IS NULL OR new_quantity > 0),
    new_scrap_percent  NUMERIC(5,2)   CHECK (new_scrap_percent IS NULL OR (new_scrap_percent >= 0 AND new_scrap_percent < 100)),
    notes              VARCHAR(300),
    CONSTRAINT uq_prd_eco_lines UNIQUE (eco_id, line_no)
);

CREATE INDEX IF NOT EXISTS ix_prd_eco_orders_item ON prd.eco_orders (item_id, status_code);
