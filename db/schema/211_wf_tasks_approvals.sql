-- پیچا R292 — موتور گردش کار (فاز ۲: تایید و کار انسانی).
-- کار/تایید هر مرحله، گیرندگان (ترتیبی/هم‌زمان)، تصمیم‌ها (ثبت تغییرناپذیر)، تفویض اختیار و اتصال کارمند به کاربر سامانه.
-- برگشت: db/rollback/211_wf_tasks_approvals_down.sql

CREATE TABLE IF NOT EXISTS wf.tasks (
    task_id                BIGSERIAL     PRIMARY KEY,
    company_id             INT           NOT NULL REFERENCES core.companies(company_id),
    instance_id            BIGINT        NULL REFERENCES wf.instances(instance_id),
    node_id                VARCHAR(60)   NULL,
    token_id               VARCHAR(30)   NULL,
    visit                  INT           NOT NULL DEFAULT 1,
    kind                   VARCHAR(10)   NOT NULL CHECK (kind IN ('APPROVAL', 'TASK')),
    title                  VARCHAR(300)  NOT NULL,
    instructions           VARCHAR(2000) NULL,
    entity_type            VARCHAR(50)   NULL,
    entity_id              BIGINT        NULL,
    mode                   VARCHAR(12)   NOT NULL DEFAULT 'ANY'
        CHECK (mode IN ('SINGLE', 'ANY', 'ALL', 'PERCENT', 'SEQUENTIAL')),
    required_percent       SMALLINT      NULL,
    options                JSONB         NOT NULL DEFAULT '{}'::jsonb,
    form_fields            JSONB         NOT NULL DEFAULT '[]'::jsonb,
    result                 JSONB         NOT NULL DEFAULT '{}'::jsonb,
    status_code            VARCHAR(10)   NOT NULL DEFAULT 'OPEN'
        CHECK (status_code IN ('OPEN', 'APPROVED', 'REJECTED', 'CHANGES', 'DONE', 'CANCELLED', 'EXPIRED')),
    priority_code          VARCHAR(10)   NOT NULL DEFAULT 'NORMAL',
    requested_by_user_id   INT           NULL REFERENCES sec.users(user_id),
    due_at                 TIMESTAMPTZ   NULL,
    created_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),
    closed_at              TIMESTAMPTZ   NULL,
    closed_by_user_id      INT           NULL REFERENCES sec.users(user_id),
    resumed_at             TIMESTAMPTZ   NULL,
    row_version            INT           NOT NULL DEFAULT 1
);
-- هر بار رسیدن به یک مرحله فقط یک کار (اجرای دوباره پس از قطعی کار تکراری نمی‌سازد)
CREATE UNIQUE INDEX IF NOT EXISTS ux_wf_tasks_visit ON wf.tasks (instance_id, node_id, visit) WHERE instance_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_wf_tasks_open ON wf.tasks (company_id, status_code);
CREATE INDEX IF NOT EXISTS ix_wf_tasks_entity ON wf.tasks (company_id, entity_type, entity_id);

CREATE TABLE IF NOT EXISTS wf.task_assignees (
    assignee_id            BIGSERIAL     PRIMARY KEY,
    task_id                BIGINT        NOT NULL REFERENCES wf.tasks(task_id) ON DELETE CASCADE,
    user_id                INT           NOT NULL REFERENCES sec.users(user_id),
    seq                    SMALLINT      NOT NULL DEFAULT 1,
    status_code            VARCHAR(10)   NOT NULL DEFAULT 'ACTIVE'
        CHECK (status_code IN ('QUEUED', 'ACTIVE', 'DECIDED', 'SKIPPED', 'DELEGATED', 'CANCELLED')),
    decision               VARCHAR(10)   NULL,
    original_user_id       INT           NULL REFERENCES sec.users(user_id),
    delegation_id          INT           NULL,
    activated_at           TIMESTAMPTZ   NULL,
    decided_at             TIMESTAMPTZ   NULL,
    UNIQUE (task_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_wf_task_assignees_user ON wf.task_assignees (user_id, status_code);

-- ثبت تغییرناپذیر تصمیم‌ها و یادداشت‌ها (تاریخچه)
CREATE TABLE IF NOT EXISTS wf.task_decisions (
    decision_id            BIGSERIAL     PRIMARY KEY,
    task_id                BIGINT        NOT NULL REFERENCES wf.tasks(task_id) ON DELETE CASCADE,
    user_id                INT           NULL REFERENCES sec.users(user_id),
    on_behalf_of_user_id   INT           NULL REFERENCES sec.users(user_id),
    decision               VARCHAR(10)   NOT NULL
        CHECK (decision IN ('APPROVE', 'REJECT', 'CHANGES', 'DONE', 'COMMENT', 'DELEGATE', 'REASSIGN', 'CANCEL')),
    comment                VARCHAR(2000) NULL,
    data                   JSONB         NOT NULL DEFAULT '{}'::jsonb,
    client_ref             VARCHAR(80)   NULL,
    channel                VARCHAR(10)   NOT NULL DEFAULT 'DESKTOP',
    created_at             TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_wf_task_decisions_client ON wf.task_decisions (task_id, client_ref) WHERE client_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_wf_task_decisions_task ON wf.task_decisions (task_id);

-- تفویض اختیار (مرخصی/مأموریت): کارهای تازهٔ «از» در بازهٔ تاریخ به «به» می‌رسد
CREATE TABLE IF NOT EXISTS wf.delegations (
    delegation_id          SERIAL        PRIMARY KEY,
    company_id             INT           NOT NULL REFERENCES core.companies(company_id),
    from_user_id           INT           NOT NULL REFERENCES sec.users(user_id),
    to_user_id             INT           NOT NULL REFERENCES sec.users(user_id),
    starts_on              DATE          NOT NULL,
    ends_on                DATE          NOT NULL,
    definition_id          INT           NULL REFERENCES wf.definitions(definition_id) ON DELETE CASCADE,
    entity_type            VARCHAR(50)   NULL,
    reason                 VARCHAR(500)  NULL,
    is_active              BOOLEAN       NOT NULL DEFAULT TRUE,
    created_by_user_id     INT           NULL REFERENCES sec.users(user_id),
    created_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CHECK (from_user_id <> to_user_id),
    CHECK (ends_on >= starts_on)
);
CREATE INDEX IF NOT EXISTS ix_wf_delegations_from ON wf.delegations (company_id, from_user_id) WHERE is_active;

-- کاربر سامانهٔ هر کارمند (برای مسیر «مدیر مستقیم» و «مدیر واحد سازمانی»)
ALTER TABLE hr.employees ADD COLUMN IF NOT EXISTS user_id INT NULL REFERENCES sec.users(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_hr_employees_user ON hr.employees (company_id, user_id) WHERE user_id IS NOT NULL;
