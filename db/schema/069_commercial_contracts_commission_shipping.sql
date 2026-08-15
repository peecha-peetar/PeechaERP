-- پیچا | مدیریتِ بازرگانی — مرحلهٔ ۲: قرارداد، کمیسیون، حمل، اشتراک.
-- پیش‌نیاز: 067_commercial_documents.sql، 068_commercial_partners.sql

CREATE TABLE comm.commercial_contracts (
    contract_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    contract_type_code VARCHAR(10) NOT NULL CHECK (contract_type_code IN ('SALES', 'PURCHASE')),
    counterparty_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    item_id INT NULL REFERENCES inv.items(item_id),  -- خالی یعنی سطحِ کلِ طرفِ‌حساب
    committed_quantity NUMERIC(18,6) NULL,
    consumed_quantity NUMERIC(18,6) NOT NULL DEFAULT 0,
    contract_price NUMERIC(18,6) NULL,
    valid_from DATE NOT NULL,
    valid_to DATE NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status_code IN ('ACTIVE', 'FULFILLED', 'EXPIRED', 'CANCELLED'))
);

CREATE TABLE comm.commission_entries (
    entry_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_line_id BIGINT NOT NULL REFERENCES comm.commercial_document_lines(line_id),
    rep_detail_account_id INT NOT NULL REFERENCES comm.sales_representatives(rep_detail_account_id),
    rule_id INT NOT NULL REFERENCES comm.commission_rules(rule_id),
    base_amount NUMERIC(18,2) NOT NULL,
    commission_amount NUMERIC(18,2) NOT NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'PENDING'
        CHECK (status_code IN ('PENDING', 'APPROVED', 'PAID', 'REVERSED')),
    payment_journal_entry_id INT NULL REFERENCES acc.journal_entries(journal_entry_id)
);

CREATE TABLE comm.shipments (
    shipment_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES comm.commercial_documents(document_id),
    carrier_name VARCHAR(150) NULL,
    tracking_no VARCHAR(100) NULL,
    shipping_method_code VARCHAR(15) NOT NULL
        CHECK (shipping_method_code IN ('PICKUP', 'COURIER', 'POST', 'FREIGHT')),
    shipping_cost NUMERIC(18,2) NOT NULL DEFAULT 0,
    billed_to_customer BOOLEAN NOT NULL DEFAULT FALSE,
    status_code VARCHAR(15) NOT NULL DEFAULT 'PENDING'
        CHECK (status_code IN ('PENDING', 'SHIPPED', 'DELIVERED', 'FAILED')),
    shipped_at TIMESTAMPTZ NULL,
    delivered_at TIMESTAMPTZ NULL
);

-- صورت‌حسابِ خودکارِ تکرارشونده (مرحلهٔ ۶، بخشِ ۶).
CREATE TABLE comm.recurring_billing_schedules (
    schedule_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    contract_id INT NULL REFERENCES comm.commercial_contracts(contract_id),
    customer_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    interval_code VARCHAR(10) NOT NULL CHECK (interval_code IN ('MONTHLY', 'QUARTERLY', 'ANNUAL')),
    next_run_date DATE NOT NULL,
    auto_post BOOLEAN NOT NULL DEFAULT FALSE,
    last_generated_document_id BIGINT NULL REFERENCES comm.commercial_documents(document_id),
    status_code VARCHAR(15) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status_code IN ('ACTIVE', 'PAUSED', 'CANCELLED'))
);

CREATE INDEX ix_comm_recurring_schedules_due
    ON comm.recurring_billing_schedules (next_run_date)
    WHERE status_code = 'ACTIVE';
