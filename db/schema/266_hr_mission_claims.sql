-- R381: حق مأموریت و هزینهٔ مأموریت — صورت‌حساب روی مرخصی «مأموریت» تاییدشده؛ جدا از محاسبهٔ حقوق.
CREATE TABLE IF NOT EXISTS hr.mission_settings (
    company_id                 INT            PRIMARY KEY REFERENCES core.companies(company_id) ON DELETE CASCADE,
    per_diem_method            VARCHAR(10)    NOT NULL DEFAULT 'FIXED' CHECK (per_diem_method IN ('FIXED', 'PERCENT')),
    daily_amount               NUMERIC(18,2)  NOT NULL DEFAULT 0 CHECK (daily_amount >= 0),
    daily_percent              NUMERIC(6,2)   NOT NULL DEFAULT 0 CHECK (daily_percent >= 0),
    expense_gl_account_id      INT            REFERENCES acc.chart_of_accounts(account_id),
    expense_detail_account_id  INT            REFERENCES acc.detail_accounts(detail_account_id),
    payable_gl_account_id      INT            REFERENCES acc.chart_of_accounts(account_id),
    updated_by_user_id         INT            REFERENCES sec.users(user_id),
    updated_at                 TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hr.mission_claims (
    claim_id             BIGSERIAL      PRIMARY KEY,
    company_id           INT            NOT NULL REFERENCES core.companies(company_id),
    claim_no             INT            NOT NULL,
    employee_id          INT            NOT NULL REFERENCES hr.employees(employee_id),
    leave_request_id     BIGINT         NOT NULL UNIQUE REFERENCES hr.leave_requests(leave_request_id),
    destination          VARCHAR(200)   NOT NULL,
    purpose              VARCHAR(500),
    days                 NUMERIC(6,2)   NOT NULL CHECK (days > 0),
    daily_rate           NUMERIC(18,2)  NOT NULL DEFAULT 0 CHECK (daily_rate >= 0),
    per_diem_amount      NUMERIC(18,2)  NOT NULL DEFAULT 0,
    expenses_amount      NUMERIC(18,2)  NOT NULL DEFAULT 0,
    status_code          VARCHAR(10)    NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'POSTED')),
    created_by_user_id   INT            REFERENCES sec.users(user_id),
    created_at           TIMESTAMPTZ    NOT NULL DEFAULT now(),
    decided_by_user_id   INT            REFERENCES sec.users(user_id),
    decided_at           TIMESTAMPTZ,
    decision_note        VARCHAR(500),
    journal_entry_id     INT            REFERENCES acc.journal_entries(journal_entry_id) ON DELETE SET NULL,
    posted_at            TIMESTAMPTZ,
    CONSTRAINT uq_hr_mission_claims_no UNIQUE (company_id, claim_no)
);
CREATE INDEX IF NOT EXISTS ix_hr_mission_claims_status ON hr.mission_claims (company_id, status_code);

CREATE TABLE IF NOT EXISTS hr.mission_claim_expenses (
    expense_id    BIGSERIAL      PRIMARY KEY,
    claim_id      BIGINT         NOT NULL REFERENCES hr.mission_claims(claim_id) ON DELETE CASCADE,
    expense_type  VARCHAR(10)    NOT NULL CHECK (expense_type IN ('TRANSPORT', 'LODGING', 'MEALS', 'OTHER')),
    description   VARCHAR(300),
    receipt_no    VARCHAR(50),
    amount        NUMERIC(18,2)  NOT NULL CHECK (amount > 0)
);
