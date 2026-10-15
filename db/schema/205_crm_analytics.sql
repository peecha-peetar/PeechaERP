-- پیچا R283 — تحلیل مشتری CRM (فاز ۴): سگمنت پویا، کش امتیازها (RFM، سلامت، ریسک ریزش، CLV) و تنظیمات.
-- crm.customer_scores فقط کش قابل محاسبهٔ مجدد از فروش/حسابداری است، نه منبع حقیقت. برگشت: db/rollback/205_crm_analytics_down.sql

CREATE TABLE IF NOT EXISTS crm.settings (
    company_id  INT         PRIMARY KEY REFERENCES core.companies(company_id),
    options     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS crm.segments (
    segment_id          SERIAL        PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    code                VARCHAR(30)   NOT NULL,
    name                VARCHAR(150)  NOT NULL,
    description         VARCHAR(500)  NULL,
    rule                JSONB         NOT NULL DEFAULT '{"all": []}'::jsonb,
    is_system           BOOLEAN       NOT NULL DEFAULT FALSE,
    is_active           BOOLEAN       NOT NULL DEFAULT TRUE,
    member_count        INT           NULL,
    refreshed_at        TIMESTAMPTZ   NULL,
    created_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS crm.customer_scores (
    customer_detail_account_id  INT           PRIMARY KEY REFERENCES acc.detail_accounts(detail_account_id),
    company_id                  INT           NOT NULL REFERENCES core.companies(company_id),
    recency_days                INT           NULL,
    frequency_365               INT           NOT NULL DEFAULT 0,
    monetary_365                NUMERIC(18,2) NOT NULL DEFAULT 0,
    sales_90d                   NUMERIC(18,2) NOT NULL DEFAULT 0,
    invoice_count_total         INT           NOT NULL DEFAULT 0,
    first_purchase              DATE          NULL,
    last_purchase               DATE          NULL,
    avg_gap_days                NUMERIC(8,1)  NULL,
    r_score                     SMALLINT      NULL,
    f_score                     SMALLINT      NULL,
    m_score                     SMALLINT      NULL,
    rfm_segment                 VARCHAR(20)   NULL,
    health_score                SMALLINT      NOT NULL DEFAULT 0,
    health_band                 VARCHAR(10)   NOT NULL DEFAULT 'ATTENTION',
    churn_risk                  SMALLINT      NOT NULL DEFAULT 0,
    churn_band                  VARCHAR(10)   NOT NULL DEFAULT 'LOW',
    clv_historical              NUMERIC(18,2) NOT NULL DEFAULT 0,
    clv_predicted               NUMERIC(18,2) NOT NULL DEFAULT 0,
    overdue_amount              NUMERIC(18,2) NOT NULL DEFAULT 0,
    open_complaints             INT           NOT NULL DEFAULT 0,
    activities_90d              INT           NOT NULL DEFAULT 0,
    factors                     JSONB         NOT NULL DEFAULT '{}'::jsonb,
    next_best_action            VARCHAR(300)  NULL,
    computed_at                 TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_crm_scores_company_health ON crm.customer_scores (company_id, health_band);
CREATE INDEX IF NOT EXISTS ix_crm_scores_company_churn ON crm.customer_scores (company_id, churn_risk DESC);
CREATE INDEX IF NOT EXISTS ix_crm_scores_company_rfm ON crm.customer_scores (company_id, rfm_segment);

-- پرس‌وجوهای تحلیلی روی فاکتورهای ثبت‌شدهٔ هر مشتری
CREATE INDEX IF NOT EXISTS ix_comm_docs_crm_customer_sales
    ON comm.commercial_documents (company_id, counterparty_detail_account_id, document_type_code, status_code, document_date);
