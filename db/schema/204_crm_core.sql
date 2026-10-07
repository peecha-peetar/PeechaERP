-- پیچا R281 — هستهٔ CRM (فاز ۲): سرنخ، قیف فروش، فرصت و توسعهٔ جدول فعالیت.
-- فقط افزودنی: مشتری، سند فروش، کالا و کاربر همان جدول‌های موجودند و فقط ارجاع داده می‌شوند.
-- comm.customer_activities جدول واحد فعالیت می‌ماند (نوع‌ها و ستون‌های تازه، بدون تغییر رفتار قبلی).
-- برگشت: db/rollback/204_crm_core_down.sql

CREATE SCHEMA IF NOT EXISTS crm;

CREATE TABLE IF NOT EXISTS crm.lead_sources (
    source_id   SERIAL       PRIMARY KEY,
    company_id  INT          NULL REFERENCES core.companies(company_id),
    code        VARCHAR(30)  NOT NULL,
    name        VARCHAR(100) NOT NULL,
    sort_order  SMALLINT     NOT NULL DEFAULT 100,
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_crm_lead_sources_code ON crm.lead_sources (COALESCE(company_id, 0), code);

INSERT INTO crm.lead_sources (company_id, code, name, sort_order)
SELECT NULL, v.code, v.name, v.ord FROM (VALUES
    ('WEBSITE', 'وب‌سایت', 10), ('MOBILE_APP', 'اپلیکیشن موبایل', 20), ('INSTAGRAM', 'اینستاگرام', 30),
    ('WHATSAPP', 'واتس‌اپ', 40), ('TELEGRAM', 'تلگرام', 50), ('REFERRAL', 'معرفی مشتری', 60),
    ('PHONE', 'تماس تلفنی', 70), ('EXHIBITION', 'نمایشگاه', 80), ('ADVERTISING', 'تبلیغات', 90),
    ('STORE', 'فروشگاه', 100), ('VISITOR', 'ویزیتور', 110), ('OTHER', 'سایر', 200)
) AS v(code, name, ord)
WHERE NOT EXISTS (SELECT 1 FROM crm.lead_sources s WHERE s.company_id IS NULL AND s.code = v.code);

CREATE TABLE IF NOT EXISTS crm.pipelines (
    pipeline_id  SERIAL       PRIMARY KEY,
    company_id   INT          NOT NULL REFERENCES core.companies(company_id),
    code         VARCHAR(30)  NOT NULL,
    name         VARCHAR(100) NOT NULL,
    is_default   BOOLEAN      NOT NULL DEFAULT FALSE,
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS crm.pipeline_stages (
    stage_id             SERIAL       PRIMARY KEY,
    pipeline_id          INT          NOT NULL REFERENCES crm.pipelines(pipeline_id),
    code                 VARCHAR(30)  NOT NULL,
    name                 VARCHAR(100) NOT NULL,
    sort_order           SMALLINT     NOT NULL DEFAULT 0,
    probability_percent  NUMERIC(5,2) NOT NULL DEFAULT 0 CHECK (probability_percent BETWEEN 0 AND 100),
    stage_type           VARCHAR(5)   NOT NULL DEFAULT 'OPEN' CHECK (stage_type IN ('OPEN', 'WON', 'LOST')),
    sla_hours            INT          NULL CHECK (sla_hours IS NULL OR sla_hours > 0),
    required_fields      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    next_action          VARCHAR(300) NULL,
    auto_activity        JSONB        NULL,
    is_active            BOOLEAN      NOT NULL DEFAULT TRUE,
    UNIQUE (pipeline_id, code)
);

CREATE TABLE IF NOT EXISTS crm.leads (
    lead_id                               BIGSERIAL     PRIMARY KEY,
    company_id                            INT           NOT NULL REFERENCES core.companies(company_id),
    lead_no                               INT           NOT NULL,
    full_name                             VARCHAR(150)  NOT NULL,
    company_name                          VARCHAR(150)  NULL,
    mobile                                VARCHAR(20)   NULL,
    phone                                 VARCHAR(20)   NULL,
    email                                 VARCHAR(150)  NULL,
    source_id                             INT           NULL REFERENCES crm.lead_sources(source_id),
    interested_item_id                    INT           NULL REFERENCES inv.items(item_id),
    interested_text                       VARCHAR(300)  NULL,
    estimated_value                       NUMERIC(18,2) NULL,
    owner_user_id                         INT           NULL REFERENCES sec.users(user_id),
    status_code                           VARCHAR(12)   NOT NULL DEFAULT 'NEW'
        CHECK (status_code IN ('NEW', 'CONTACTED', 'QUALIFIED', 'UNQUALIFIED', 'CONVERTED', 'LOST')),
    score                                 SMALLINT      NOT NULL DEFAULT 0,
    score_band                            VARCHAR(8)    NOT NULL DEFAULT 'COLD'
        CHECK (score_band IN ('COLD', 'WARM', 'HOT', 'VERY_HOT')),
    city                                  VARCHAR(100)  NULL,
    province                              VARCHAR(100)  NULL,
    industry                              VARCHAR(100)  NULL,
    notes                                 VARCHAR(2000) NULL,
    next_action                           VARCHAR(300)  NULL,
    next_action_date                      DATE          NULL,
    last_activity_at                      TIMESTAMPTZ   NULL,
    converted_customer_detail_account_id  INT           NULL REFERENCES acc.detail_accounts(detail_account_id),
    converted_opportunity_id              BIGINT        NULL,
    converted_at                          TIMESTAMPTZ   NULL,
    lost_reason                           VARCHAR(300)  NULL,
    created_by_user_id                    INT           NOT NULL REFERENCES sec.users(user_id),
    created_at                            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at                            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (company_id, lead_no)
);
CREATE INDEX IF NOT EXISTS ix_crm_leads_status ON crm.leads (company_id, status_code, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_crm_leads_owner ON crm.leads (owner_user_id, status_code);
CREATE INDEX IF NOT EXISTS ix_crm_leads_mobile ON crm.leads (company_id, mobile);

CREATE TABLE IF NOT EXISTS crm.opportunities (
    opportunity_id               BIGSERIAL     PRIMARY KEY,
    company_id                   INT           NOT NULL REFERENCES core.companies(company_id),
    opportunity_no               INT           NOT NULL,
    title                        VARCHAR(200)  NOT NULL,
    customer_detail_account_id   INT           NULL REFERENCES acc.detail_accounts(detail_account_id),
    lead_id                      BIGINT        NULL REFERENCES crm.leads(lead_id),
    owner_user_id                INT           NULL REFERENCES sec.users(user_id),
    pipeline_id                  INT           NOT NULL REFERENCES crm.pipelines(pipeline_id),
    stage_id                     INT           NOT NULL REFERENCES crm.pipeline_stages(stage_id),
    amount                       NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (amount >= 0),
    probability_percent          NUMERIC(5,2)  NOT NULL DEFAULT 0 CHECK (probability_percent BETWEEN 0 AND 100),
    expected_close_date          DATE          NULL,
    source_id                    INT           NULL REFERENCES crm.lead_sources(source_id),
    description                  VARCHAR(2000) NULL,
    status_code                  VARCHAR(5)    NOT NULL DEFAULT 'OPEN' CHECK (status_code IN ('OPEN', 'WON', 'LOST')),
    lost_reason                  VARCHAR(300)  NULL,
    stage_entered_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),
    closed_at                    TIMESTAMPTZ   NULL,
    created_by_user_id           INT           NOT NULL REFERENCES sec.users(user_id),
    created_at                   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at                   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (company_id, opportunity_no),
    CHECK (customer_detail_account_id IS NOT NULL OR lead_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_crm_opps_stage ON crm.opportunities (company_id, pipeline_id, stage_id, status_code);
CREATE INDEX IF NOT EXISTS ix_crm_opps_owner ON crm.opportunities (owner_user_id, status_code);
CREATE INDEX IF NOT EXISTS ix_crm_opps_customer ON crm.opportunities (customer_detail_account_id);
CREATE INDEX IF NOT EXISTS ix_crm_opps_close ON crm.opportunities (company_id, status_code, expected_close_date);

ALTER TABLE crm.leads DROP CONSTRAINT IF EXISTS fk_crm_leads_opportunity;
ALTER TABLE crm.leads ADD CONSTRAINT fk_crm_leads_opportunity
    FOREIGN KEY (converted_opportunity_id) REFERENCES crm.opportunities(opportunity_id);

CREATE TABLE IF NOT EXISTS crm.opportunity_lines (
    line_id          BIGSERIAL     PRIMARY KEY,
    opportunity_id   BIGINT        NOT NULL REFERENCES crm.opportunities(opportunity_id) ON DELETE CASCADE,
    item_id          INT           NULL REFERENCES inv.items(item_id),
    description      VARCHAR(300)  NULL,
    quantity         NUMERIC(18,6) NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price       NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    discount_amount  NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    CHECK (item_id IS NOT NULL OR description IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_crm_opp_lines ON crm.opportunity_lines (opportunity_id);

-- پیوند فرصت ← سند واقعی فروش (پیش‌فاکتور/سفارش/فاکتور). فقط ارجاع؛ سند در comm.commercial_documents است.
CREATE TABLE IF NOT EXISTS crm.opportunity_documents (
    opportunity_id  BIGINT      NOT NULL REFERENCES crm.opportunities(opportunity_id) ON DELETE CASCADE,
    document_id     BIGINT      NOT NULL REFERENCES comm.commercial_documents(document_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (opportunity_id, document_id)
);
CREATE INDEX IF NOT EXISTS ix_crm_opp_docs_document ON crm.opportunity_documents (document_id);

-- comm.customer_activities: جدول واحد فعالیت CRM
ALTER TABLE comm.customer_activities ALTER COLUMN customer_detail_account_id DROP NOT NULL;
ALTER TABLE comm.customer_activities
    ADD COLUMN IF NOT EXISTS lead_id            BIGINT        NULL REFERENCES crm.leads(lead_id),
    ADD COLUMN IF NOT EXISTS opportunity_id     BIGINT        NULL REFERENCES crm.opportunities(opportunity_id),
    ADD COLUMN IF NOT EXISTS ticket_id          BIGINT        NULL REFERENCES comm.service_tickets(ticket_id),
    ADD COLUMN IF NOT EXISTS customer_visit_id  BIGINT        NULL REFERENCES comm.customer_visits(customer_visit_id),
    ADD COLUMN IF NOT EXISTS start_at           TIMESTAMPTZ   NULL,
    ADD COLUMN IF NOT EXISTS duration_minutes   INT           NULL CHECK (duration_minutes IS NULL OR duration_minutes >= 0),
    ADD COLUMN IF NOT EXISTS priority_code      VARCHAR(10)   NOT NULL DEFAULT 'NORMAL',
    ADD COLUMN IF NOT EXISTS result_text        VARCHAR(1000) NULL,
    ADD COLUMN IF NOT EXISTS next_action        VARCHAR(300)  NULL,
    ADD COLUMN IF NOT EXISTS next_action_date   DATE          NULL,
    ADD COLUMN IF NOT EXISTS updated_at         TIMESTAMPTZ   NULL;
ALTER TABLE comm.customer_activities DROP CONSTRAINT IF EXISTS customer_activities_activity_type_code_check;
ALTER TABLE comm.customer_activities ADD CONSTRAINT customer_activities_activity_type_code_check CHECK (
    activity_type_code IN ('COMPLAINT', 'MEETING', 'OPPORTUNITY', 'TASK', 'CALL', 'VISIT', 'FOLLOW_UP', 'EMAIL',
                           'MESSAGE', 'REMINDER', 'NOTE'));
ALTER TABLE comm.customer_activities DROP CONSTRAINT IF EXISTS ck_customer_activities_party;
ALTER TABLE comm.customer_activities ADD CONSTRAINT ck_customer_activities_party
    CHECK (customer_detail_account_id IS NOT NULL OR lead_id IS NOT NULL);
ALTER TABLE comm.customer_activities DROP CONSTRAINT IF EXISTS ck_customer_activities_priority;
ALTER TABLE comm.customer_activities ADD CONSTRAINT ck_customer_activities_priority
    CHECK (priority_code IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL'));
CREATE INDEX IF NOT EXISTS ix_comm_customer_activities_due
    ON comm.customer_activities (company_id, assigned_to_user_id, status_code, due_date);
CREATE INDEX IF NOT EXISTS ix_comm_customer_activities_lead ON comm.customer_activities (lead_id);
CREATE INDEX IF NOT EXISTS ix_comm_customer_activities_opp ON comm.customer_activities (opportunity_id);
