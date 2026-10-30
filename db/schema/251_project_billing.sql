-- پیچا | R365: فهرست بهای پیمان و صورت‌وضعیت پروژه؛ فاکتور فروش هر صورت‌وضعیت از همان اسناد فروش ساخته می‌شود
CREATE TABLE IF NOT EXISTS prj.contract_items (
    contract_item_id   INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id         INT           NOT NULL REFERENCES prj.projects(project_id) ON DELETE CASCADE,
    code               VARCHAR(30)   NOT NULL,
    description        VARCHAR(300)  NOT NULL,
    unit               VARCHAR(30)   NOT NULL,
    contract_quantity  NUMERIC(18,3) NOT NULL CHECK (contract_quantity > 0),
    unit_price         NUMERIC(18,2) NOT NULL CHECK (unit_price >= 0),
    sort_order         INT           NOT NULL DEFAULT 0,
    CONSTRAINT uq_prj_contract_items UNIQUE (project_id, code)
);

CREATE TABLE IF NOT EXISTS prj.billing_settings (
    project_id           INT           PRIMARY KEY REFERENCES prj.projects(project_id) ON DELETE CASCADE,
    service_item_id      INT           REFERENCES inv.items(item_id),
    retention_percent    NUMERIC(5,2)  NOT NULL DEFAULT 0 CHECK (retention_percent BETWEEN 0 AND 100),
    insurance_percent    NUMERIC(5,2)  NOT NULL DEFAULT 0 CHECK (insurance_percent BETWEEN 0 AND 100),
    advance_amount       NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (advance_amount >= 0),
    advance_recovery_percent NUMERIC(5,2) NOT NULL DEFAULT 0 CHECK (advance_recovery_percent BETWEEN 0 AND 100)
);

CREATE TABLE IF NOT EXISTS prj.progress_statements (
    statement_id         INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    project_id           INT           NOT NULL REFERENCES prj.projects(project_id),
    statement_no         INT           NOT NULL,
    period_end           DATE          NOT NULL,
    status_code          VARCHAR(20)   NOT NULL DEFAULT 'DRAFT' CHECK (status_code IN ('DRAFT', 'CONFIRMED', 'INVOICED', 'CANCELLED')),
    gross_to_date        NUMERIC(18,2) NOT NULL DEFAULT 0,
    previous_gross       NUMERIC(18,2) NOT NULL DEFAULT 0,
    retention_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,
    insurance_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,
    advance_recovery     NUMERIC(18,2) NOT NULL DEFAULT 0,
    notes                VARCHAR(500),
    sales_invoice_id     INT           REFERENCES comm.commercial_documents(document_id),
    created_by_user_id   INT           REFERENCES sec.users(user_id),
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    confirmed_by_user_id INT           REFERENCES sec.users(user_id),
    confirmed_at         TIMESTAMPTZ,
    CONSTRAINT uq_prj_progress_statements UNIQUE (project_id, statement_no)
);

CREATE TABLE IF NOT EXISTS prj.progress_statement_lines (
    statement_id         INT           NOT NULL REFERENCES prj.progress_statements(statement_id) ON DELETE CASCADE,
    contract_item_id     INT           NOT NULL REFERENCES prj.contract_items(contract_item_id),
    cumulative_quantity  NUMERIC(18,3) NOT NULL CHECK (cumulative_quantity >= 0),
    unit_price           NUMERIC(18,2) NOT NULL CHECK (unit_price >= 0),
    PRIMARY KEY (statement_id, contract_item_id)
);
