-- پیچا | R363: مدیریت پروژه — پروژه روی همان تفصیلی «پروژه»، فاز و فعالیت (ساختار شکست کار)، پیوند فعالیت‌ها،
-- زمان‌بندی روزکاری با مسیر بحرانی و خط مبنا
CREATE SCHEMA IF NOT EXISTS prj;

CREATE TABLE IF NOT EXISTS prj.projects (
    project_id                  INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                  INT           NOT NULL REFERENCES core.companies(company_id),
    project_detail_account_id   INT           NOT NULL UNIQUE REFERENCES acc.detail_accounts(detail_account_id),
    customer_detail_account_id  INT           REFERENCES acc.detail_accounts(detail_account_id),
    manager_employee_id         INT           REFERENCES hr.employees(employee_id) ON DELETE SET NULL,
    status_code                 VARCHAR(20)   NOT NULL DEFAULT 'PLANNING'
        CHECK (status_code IN ('PLANNING', 'ACTIVE', 'ON_HOLD', 'COMPLETED', 'CANCELLED')),
    start_date                  DATE          NOT NULL,
    target_end_date             DATE,
    contract_amount             NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (contract_amount >= 0),
    description                 VARCHAR(1000),
    baseline_set_at             TIMESTAMPTZ,
    created_by_user_id          INT           REFERENCES sec.users(user_id),
    created_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT ck_prj_projects_dates CHECK (target_end_date IS NULL OR target_end_date >= start_date)
);
CREATE INDEX IF NOT EXISTS ix_prj_projects_company ON prj.projects(company_id);

CREATE TABLE IF NOT EXISTS prj.tasks (
    task_id                  INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id               INT           NOT NULL REFERENCES prj.projects(project_id) ON DELETE CASCADE,
    parent_task_id           INT           REFERENCES prj.tasks(task_id) ON DELETE CASCADE,
    sort_order               INT           NOT NULL DEFAULT 0,
    name                     VARCHAR(200)  NOT NULL,
    duration_days            INT           NOT NULL DEFAULT 1 CHECK (duration_days >= 0),
    start_no_earlier         DATE,
    responsible_employee_id  INT           REFERENCES hr.employees(employee_id) ON DELETE SET NULL,
    planned_hours            NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (planned_hours >= 0),
    planned_cost             NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (planned_cost >= 0),
    percent_complete         NUMERIC(5,2)  NOT NULL DEFAULT 0 CHECK (percent_complete BETWEEN 0 AND 100),
    actual_start             DATE,
    actual_finish            DATE,
    baseline_start           DATE,
    baseline_finish          DATE,
    baseline_cost            NUMERIC(18,2),
    notes                    VARCHAR(1000),
    CONSTRAINT ck_prj_tasks_actual CHECK (actual_finish IS NULL OR (actual_start IS NOT NULL AND actual_finish >= actual_start))
);
CREATE INDEX IF NOT EXISTS ix_prj_tasks_project ON prj.tasks(project_id);

CREATE TABLE IF NOT EXISTS prj.task_links (
    link_id              INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    predecessor_task_id  INT         NOT NULL REFERENCES prj.tasks(task_id) ON DELETE CASCADE,
    successor_task_id    INT         NOT NULL REFERENCES prj.tasks(task_id) ON DELETE CASCADE,
    link_type            VARCHAR(2)  NOT NULL DEFAULT 'FS' CHECK (link_type IN ('FS', 'SS', 'FF')),
    lag_days             INT         NOT NULL DEFAULT 0,
    CONSTRAINT uq_prj_task_links UNIQUE (predecessor_task_id, successor_task_id),
    CONSTRAINT ck_prj_task_links_self CHECK (predecessor_task_id <> successor_task_id)
);
