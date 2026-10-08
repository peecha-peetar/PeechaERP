-- پیچا R284 — بازاریابی CRM (فاز ۵): کمپین، مخاطبان کمپین (از سگمنت یا سرنخ) و نسبت‌دادن سرنخ/فرصت به کمپین.
-- ارسال پیامکی از همان comm.sms_campaigns و sms_gateway موجود انجام می‌شود. برگشت: db/rollback/206_crm_marketing_down.sql

CREATE TABLE IF NOT EXISTS crm.campaigns (
    campaign_id         SERIAL        PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    campaign_no         INT           NOT NULL,
    name                VARCHAR(150)  NOT NULL,
    campaign_type       VARCHAR(15)   NOT NULL DEFAULT 'SMS'
        CHECK (campaign_type IN ('SMS', 'EMAIL', 'WHATSAPP', 'TELEGRAM', 'CALL', 'VISIT', 'EVENT', 'ADVERTISING', 'SOCIAL', 'OTHER')),
    status_code         VARCHAR(12)   NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'SCHEDULED', 'ACTIVE', 'COMPLETED', 'CANCELLED')),
    segment_id          INT           NULL REFERENCES crm.segments(segment_id) ON DELETE SET NULL,
    lead_source_id      INT           NULL REFERENCES crm.lead_sources(source_id),
    start_date          DATE          NULL,
    end_date            DATE          NULL,
    attribution_days    INT           NOT NULL DEFAULT 30 CHECK (attribution_days >= 0),
    budget_amount       NUMERIC(18,2) NULL CHECK (budget_amount IS NULL OR budget_amount >= 0),
    actual_cost         NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (actual_cost >= 0),
    expected_revenue    NUMERIC(18,2) NULL,
    message_text        VARCHAR(1000) NULL,
    scheduled_at        TIMESTAMPTZ   NULL,
    sms_campaign_id     BIGINT        NULL REFERENCES comm.sms_campaigns(campaign_id),
    owner_user_id       INT           NULL REFERENCES sec.users(user_id),
    description         VARCHAR(1000) NULL,
    created_by_user_id  INT           NOT NULL REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (company_id, campaign_no),
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS crm.campaign_members (
    member_id                   BIGSERIAL     PRIMARY KEY,
    campaign_id                 INT           NOT NULL REFERENCES crm.campaigns(campaign_id) ON DELETE CASCADE,
    customer_detail_account_id  INT           NULL REFERENCES acc.detail_accounts(detail_account_id),
    lead_id                     BIGINT        NULL REFERENCES crm.leads(lead_id) ON DELETE CASCADE,
    contact                     VARCHAR(150)  NULL,
    status_code                 VARCHAR(12)   NOT NULL DEFAULT 'TARGETED'
        CHECK (status_code IN ('TARGETED', 'SENT', 'FAILED', 'RESPONDED', 'CONVERTED', 'OPTED_OUT')),
    responded_at                TIMESTAMPTZ   NULL,
    converted_at                TIMESTAMPTZ   NULL,
    note                        VARCHAR(500)  NULL,
    created_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CHECK (customer_detail_account_id IS NOT NULL OR lead_id IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_crm_campaign_member_customer
    ON crm.campaign_members (campaign_id, customer_detail_account_id) WHERE customer_detail_account_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_crm_campaign_member_lead
    ON crm.campaign_members (campaign_id, lead_id) WHERE lead_id IS NOT NULL AND customer_detail_account_id IS NULL;
CREATE INDEX IF NOT EXISTS ix_crm_campaign_members_customer ON crm.campaign_members (customer_detail_account_id);

ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS campaign_id INT NULL REFERENCES crm.campaigns(campaign_id) ON DELETE SET NULL;
ALTER TABLE crm.opportunities ADD COLUMN IF NOT EXISTS campaign_id INT NULL REFERENCES crm.campaigns(campaign_id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_crm_leads_campaign ON crm.leads (campaign_id) WHERE campaign_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_crm_opps_campaign ON crm.opportunities (campaign_id) WHERE campaign_id IS NOT NULL;
