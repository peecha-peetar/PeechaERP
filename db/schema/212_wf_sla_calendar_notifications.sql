-- پیچا R293 — موتور گردش کار (فاز ۳: تعهد زمانی، تقویم کاری، اعلان چندکاناله).
-- سیاست‌های تعهد زمانی و ارجاع، تعطیلات رسمی، ستون‌های تعهد زمانی کار، ترجیحات کانال اعلان هر کاربر.
-- برگشت: db/rollback/212_wf_sla_calendar_notifications_down.sql

CREATE TABLE IF NOT EXISTS wf.sla_policies (
    policy_id             SERIAL        PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    code                  VARCHAR(30)   NOT NULL,
    name                  VARCHAR(150)  NOT NULL,
    due_hours             NUMERIC(8,2)  NOT NULL CHECK (due_hours > 0),
    warn_before_hours     NUMERIC(8,2)  NULL,
    escalate_after_hours  NUMERIC(8,2)  NULL,
    escalate_to           JSONB         NOT NULL DEFAULT '[]'::jsonb,
    repeat_every_hours    NUMERIC(8,2)  NULL,
    max_escalations       SMALLINT      NOT NULL DEFAULT 2,
    business_hours        BOOLEAN       NOT NULL DEFAULT TRUE,
    is_active             BOOLEAN       NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS wf.holidays (
    holiday_id     SERIAL        PRIMARY KEY,
    company_id     INT           NOT NULL REFERENCES core.companies(company_id),
    holiday_date   DATE          NOT NULL,
    title          VARCHAR(150)  NOT NULL,
    UNIQUE (company_id, holiday_date)
);

ALTER TABLE wf.tasks ADD COLUMN IF NOT EXISTS sla_policy_id INT NULL REFERENCES wf.sla_policies(policy_id);
ALTER TABLE wf.tasks ADD COLUMN IF NOT EXISTS warn_at TIMESTAMPTZ NULL;
ALTER TABLE wf.tasks ADD COLUMN IF NOT EXISTS escalate_at TIMESTAMPTZ NULL;
ALTER TABLE wf.tasks ADD COLUMN IF NOT EXISTS escalation_level SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE wf.tasks ADD COLUMN IF NOT EXISTS sla_status VARCHAR(10) NOT NULL DEFAULT 'NONE';
ALTER TABLE wf.tasks DROP CONSTRAINT IF EXISTS ck_wf_tasks_sla_status;
ALTER TABLE wf.tasks ADD CONSTRAINT ck_wf_tasks_sla_status CHECK (sla_status IN ('NONE', 'ON_TRACK', 'AT_RISK', 'BREACHED', 'MET'));
CREATE INDEX IF NOT EXISTS ix_wf_tasks_sla ON wf.tasks (company_id, sla_status) WHERE status_code = 'OPEN';

-- ارجاع خودکار به سطح بالاتر هم در تاریخچهٔ تصمیم‌ها ثبت می‌شود
ALTER TABLE wf.task_decisions DROP CONSTRAINT IF EXISTS task_decisions_decision_check;
ALTER TABLE wf.task_decisions DROP CONSTRAINT IF EXISTS ck_wf_task_decisions_decision;
ALTER TABLE wf.task_decisions ADD CONSTRAINT ck_wf_task_decisions_decision CHECK (decision IN
    ('APPROVE', 'REJECT', 'CHANGES', 'DONE', 'COMMENT', 'DELEGATE', 'REASSIGN', 'CANCEL', 'ESCALATE'));

-- ترجیح کانال‌های اعلان هر کاربر برای هر نوع اعلان ('*' = همهٔ انواع)
CREATE TABLE IF NOT EXISTS sec.notification_preferences (
    company_id   INT          NOT NULL REFERENCES core.companies(company_id),
    user_id      INT          NOT NULL REFERENCES sec.users(user_id),
    type_code    VARCHAR(30)  NOT NULL,
    in_app       BOOLEAN      NOT NULL DEFAULT TRUE,
    desktop      BOOLEAN      NOT NULL DEFAULT TRUE,
    sms          BOOLEAN      NOT NULL DEFAULT FALSE,
    email        BOOLEAN      NOT NULL DEFAULT FALSE,
    push         BOOLEAN      NOT NULL DEFAULT FALSE,
    PRIMARY KEY (company_id, user_id, type_code)
);

ALTER TABLE sec.notifications ADD COLUMN IF NOT EXISTS priority_code VARCHAR(10) NOT NULL DEFAULT 'NORMAL';
ALTER TABLE sec.notifications ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ NULL;
-- وضعیت ارسال هر کانال بیرونی: {"sms": "PENDING|SENT|FAILED|NO_NUMBER", "email": ...}
ALTER TABLE sec.notifications ADD COLUMN IF NOT EXISTS channels JSONB NOT NULL DEFAULT '{}'::jsonb;
CREATE INDEX IF NOT EXISTS ix_sec_notifications_unread ON sec.notifications (user_id, company_id) WHERE NOT is_read;
