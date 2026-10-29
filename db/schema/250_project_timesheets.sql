-- پیچا | R364: ثبت و تایید کارکرد پروژه و نرخ ساعتی هزینهٔ کارکنان (هزینهٔ کارکرد محاسباتی است و سند حسابداری نمی‌سازد)
CREATE TABLE IF NOT EXISTS prj.labor_rates (
    rate_id      INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id   INT           NOT NULL REFERENCES core.companies(company_id),
    employee_id  INT           REFERENCES hr.employees(employee_id) ON DELETE CASCADE,
    valid_from   DATE          NOT NULL,
    hourly_cost  NUMERIC(18,2) NOT NULL CHECK (hourly_cost >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_prj_labor_rates ON prj.labor_rates(company_id, COALESCE(employee_id, 0), valid_from);

CREATE TABLE IF NOT EXISTS prj.timesheet_entries (
    entry_id            INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    project_id          INT           NOT NULL REFERENCES prj.projects(project_id),
    task_id             INT           REFERENCES prj.tasks(task_id),
    employee_id         INT           NOT NULL REFERENCES hr.employees(employee_id),
    work_date           DATE          NOT NULL,
    hours               NUMERIC(5,2)  NOT NULL CHECK (hours > 0 AND hours <= 24),
    description         VARCHAR(500),
    status_code         VARCHAR(20)   NOT NULL DEFAULT 'DRAFT' CHECK (status_code IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED')),
    hourly_cost         NUMERIC(18,2),
    decision_note       VARCHAR(500),
    created_by_user_id  INT           REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    decided_by_user_id  INT           REFERENCES sec.users(user_id),
    decided_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_prj_timesheet_project ON prj.timesheet_entries(project_id, status_code);
CREATE INDEX IF NOT EXISTS ix_prj_timesheet_employee ON prj.timesheet_entries(employee_id, work_date);
