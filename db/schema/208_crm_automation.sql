-- پیچا R287 — اتوماسیون و ارتباطات CRM (فاز ۸): قاعده‌های خودکار، الگوی پیام، دفتر پیام‌ها و گزارش اجرای قاعده.
-- ارسال پیامک از همان sms_gateway موجود؛ کانال‌های دیگر با Provider قابل اتصال. برگشت: db/rollback/208_crm_automation_down.sql

CREATE TABLE IF NOT EXISTS crm.message_templates (
    template_id  SERIAL        PRIMARY KEY,
    company_id   INT           NOT NULL REFERENCES core.companies(company_id),
    code         VARCHAR(30)   NOT NULL,
    name         VARCHAR(150)  NOT NULL,
    channel      VARCHAR(12)   NOT NULL DEFAULT 'SMS'
        CHECK (channel IN ('SMS', 'EMAIL', 'WHATSAPP', 'TELEGRAM', 'INTERNAL')),
    subject      VARCHAR(200)  NULL,
    body         VARCHAR(2000) NOT NULL,
    is_active    BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS crm.messages (
    message_id                  BIGSERIAL     PRIMARY KEY,
    company_id                  INT           NOT NULL REFERENCES core.companies(company_id),
    channel                     VARCHAR(12)   NOT NULL,
    provider_code               VARCHAR(30)   NULL,
    customer_detail_account_id  INT           NULL REFERENCES acc.detail_accounts(detail_account_id),
    lead_id                     BIGINT        NULL REFERENCES crm.leads(lead_id) ON DELETE SET NULL,
    recipient                   VARCHAR(200)  NULL,
    subject                     VARCHAR(200)  NULL,
    body                        VARCHAR(2000) NOT NULL,
    status_code                 VARCHAR(10)   NOT NULL DEFAULT 'QUEUED' CHECK (status_code IN ('QUEUED', 'SENT', 'FAILED')),
    error_message               VARCHAR(500)  NULL,
    template_id                 INT           NULL REFERENCES crm.message_templates(template_id) ON DELETE SET NULL,
    campaign_id                 INT           NULL REFERENCES crm.campaigns(campaign_id) ON DELETE SET NULL,
    rule_id                     INT           NULL,
    activity_id                 BIGINT        NULL REFERENCES comm.customer_activities(activity_id) ON DELETE SET NULL,
    created_by_user_id          INT           NULL REFERENCES sec.users(user_id),
    created_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    sent_at                     TIMESTAMPTZ   NULL
);
CREATE INDEX IF NOT EXISTS ix_crm_messages_customer ON crm.messages (customer_detail_account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_crm_messages_company ON crm.messages (company_id, created_at DESC);

CREATE TABLE IF NOT EXISTS crm.automation_rules (
    rule_id             SERIAL        PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    name                VARCHAR(150)  NOT NULL,
    trigger_code        VARCHAR(30)   NOT NULL,
    conditions          JSONB         NOT NULL DEFAULT '{}'::jsonb,
    action_code         VARCHAR(20)   NOT NULL,
    action_params       JSONB         NOT NULL DEFAULT '{}'::jsonb,
    cooldown_days       INT           NOT NULL DEFAULT 7 CHECK (cooldown_days >= 0),
    is_active           BOOLEAN       NOT NULL DEFAULT TRUE,
    last_run_at         TIMESTAMPTZ   NULL,
    run_count           INT           NOT NULL DEFAULT 0,
    created_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS crm.automation_log (
    log_id                      BIGSERIAL    PRIMARY KEY,
    rule_id                     INT          NOT NULL REFERENCES crm.automation_rules(rule_id) ON DELETE CASCADE,
    company_id                  INT          NOT NULL REFERENCES core.companies(company_id),
    entity_type                 VARCHAR(20)  NOT NULL,
    entity_id                   BIGINT       NOT NULL,
    customer_detail_account_id  INT          NULL REFERENCES acc.detail_accounts(detail_account_id),
    result                      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_crm_automation_log_entity ON crm.automation_log (rule_id, entity_type, entity_id, created_at DESC);
