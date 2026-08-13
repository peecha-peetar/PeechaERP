-- پیچا | مدیریتِ بازرگانی — مرحلهٔ ۷: پرداختِ چندروشی، وفاداری، اقساط.
-- پیش‌نیاز: 066_commercial_pos_sessions.sql، 067_commercial_documents.sql

CREATE TABLE comm.pos_payments (
    payment_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES comm.commercial_documents(document_id),
    method_code VARCHAR(15) NOT NULL
        CHECK (method_code IN ('CASH', 'CARD', 'WALLET', 'GIFT_CARD', 'STORE_CREDIT')),
    amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    reference_no VARCHAR(100) NULL
);

CREATE TABLE comm.loyalty_transactions (
    transaction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    loyalty_account_id INT NOT NULL REFERENCES comm.loyalty_accounts(loyalty_account_id),
    document_id BIGINT NULL REFERENCES comm.commercial_documents(document_id),
    points_delta INT NOT NULL DEFAULT 0,
    wallet_delta NUMERIC(18,2) NOT NULL DEFAULT 0,
    transaction_type_code VARCHAR(10) NOT NULL CHECK (transaction_type_code IN ('EARN', 'REDEEM', 'ADJUST')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- فروشِ اقساطی (مرحلهٔ ۷، بخشِ ۴).
CREATE TABLE comm.installment_plans (
    plan_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES comm.commercial_documents(document_id),
    number_of_installments SMALLINT NOT NULL CHECK (number_of_installments > 0),
    first_due_date DATE NOT NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status_code IN ('ACTIVE', 'COMPLETED', 'DEFAULTED'))
);

CREATE TABLE comm.installment_lines (
    line_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plan_id BIGINT NOT NULL REFERENCES comm.installment_plans(plan_id),
    installment_no SMALLINT NOT NULL,
    due_date DATE NOT NULL,
    amount NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    status_code VARCHAR(15) NOT NULL DEFAULT 'PENDING'
        CHECK (status_code IN ('PENDING', 'PAID', 'OVERDUE')),
    paid_journal_entry_id INT NULL REFERENCES acc.journal_entries(journal_entry_id),
    CONSTRAINT uq_comm_installment_lines UNIQUE (plan_id, installment_no)
);

CREATE INDEX ix_comm_installment_lines_due
    ON comm.installment_lines (due_date)
    WHERE status_code IN ('PENDING', 'OVERDUE');
