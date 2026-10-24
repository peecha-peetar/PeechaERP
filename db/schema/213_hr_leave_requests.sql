-- پیچا R295 — درخواست مرخصی (موجودیت حداقلی برای گردش کار «مرخصی ← مدیر ← منابع انسانی»).
-- برگشت: db/rollback/213_hr_leave_requests_down.sql

CREATE TABLE IF NOT EXISTS hr.leave_requests (
    leave_request_id      BIGSERIAL     PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    employee_id           INT           NOT NULL REFERENCES hr.employees(employee_id),
    leave_type            VARCHAR(10)   NOT NULL DEFAULT 'ANNUAL'
        CHECK (leave_type IN ('ANNUAL', 'SICK', 'UNPAID', 'HOURLY', 'MISSION')),
    from_date             DATE          NOT NULL,
    to_date               DATE          NOT NULL,
    hours                 NUMERIC(6,2)  NULL,
    days                  NUMERIC(6,2)  NOT NULL DEFAULT 0,
    reason                VARCHAR(1000) NULL,
    status_code           VARCHAR(10)   NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED')),
    requested_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    decided_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    decided_at            TIMESTAMPTZ   NULL,
    decision_note         VARCHAR(500)  NULL,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CHECK (to_date >= from_date)
);
CREATE INDEX IF NOT EXISTS ix_hr_leave_requests_employee ON hr.leave_requests (company_id, employee_id, from_date);
