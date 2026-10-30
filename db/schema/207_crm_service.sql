-- پیچا R285 — خدمات مشتری CRM (فاز ۶): تیکت و شکایت روی همان comm.service_tickets خدمات پس از فروش، با SLA و رضایت.
-- ستون‌ها فقط افزوده می‌شوند و رفتار تیکت‌های خدمات/گارانتی موجود تغییر نمی‌کند. برگشت: db/rollback/207_crm_service_down.sql

CREATE TABLE IF NOT EXISTS crm.sla_policies (
    sla_policy_id         SERIAL       PRIMARY KEY,
    company_id            INT          NOT NULL REFERENCES core.companies(company_id),
    name                  VARCHAR(150) NOT NULL,
    ticket_type           VARCHAR(15)  NULL,
    priority_code         VARCHAR(10)  NULL CHECK (priority_code IS NULL OR priority_code IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')),
    first_response_hours  NUMERIC(8,2) NOT NULL CHECK (first_response_hours > 0),
    resolution_hours      NUMERIC(8,2) NOT NULL CHECK (resolution_hours > 0),
    escalate_to_user_id   INT          NULL REFERENCES sec.users(user_id),
    is_active             BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CHECK (resolution_hours >= first_response_hours)
);
CREATE INDEX IF NOT EXISTS ix_crm_sla_policies_company ON crm.sla_policies (company_id) WHERE is_active;

ALTER TABLE comm.service_tickets
    ADD COLUMN IF NOT EXISTS company_id           INT          NULL REFERENCES core.companies(company_id),
    ADD COLUMN IF NOT EXISTS ticket_no            INT          NULL,
    ADD COLUMN IF NOT EXISTS ticket_type          VARCHAR(15)  NOT NULL DEFAULT 'SERVICE',
    ADD COLUMN IF NOT EXISTS priority_code        VARCHAR(10)  NOT NULL DEFAULT 'NORMAL',
    ADD COLUMN IF NOT EXISTS channel_code         VARCHAR(15)  NULL,
    ADD COLUMN IF NOT EXISTS category             VARCHAR(100) NULL,
    ADD COLUMN IF NOT EXISTS related_document_id  BIGINT       NULL REFERENCES comm.commercial_documents(document_id),
    ADD COLUMN IF NOT EXISTS sla_policy_id        INT          NULL REFERENCES crm.sla_policies(sla_policy_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS first_response_due_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS resolution_due_at    TIMESTAMPTZ  NULL,
    ADD COLUMN IF NOT EXISTS first_responded_at   TIMESTAMPTZ  NULL,
    ADD COLUMN IF NOT EXISTS resolved_at          TIMESTAMPTZ  NULL,
    ADD COLUMN IF NOT EXISTS sla_breached         BOOLEAN      NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS escalation_level     SMALLINT     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS escalated_at         TIMESTAMPTZ  NULL,
    ADD COLUMN IF NOT EXISTS resolution_text      TEXT         NULL,
    ADD COLUMN IF NOT EXISTS satisfaction_score   SMALLINT     NULL,
    ADD COLUMN IF NOT EXISTS satisfaction_comment VARCHAR(500) NULL,
    ADD COLUMN IF NOT EXISTS created_by_user_id   INT          NULL REFERENCES sec.users(user_id),
    ADD COLUMN IF NOT EXISTS updated_at           TIMESTAMPTZ  NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_comm_service_tickets_crm_type') THEN
        ALTER TABLE comm.service_tickets
            ADD CONSTRAINT ck_comm_service_tickets_crm_type CHECK (ticket_type IN
                ('SERVICE', 'COMPLAINT', 'REQUEST', 'INQUIRY', 'SUPPORT', 'RETURN', 'SUGGESTION')),
            ADD CONSTRAINT ck_comm_service_tickets_crm_priority CHECK (priority_code IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')),
            ADD CONSTRAINT ck_comm_service_tickets_crm_satisfaction CHECK (satisfaction_score IS NULL OR satisfaction_score BETWEEN 1 AND 5);
    END IF;
END $$;

-- تیکت‌های موجود: شرکت از حساب تفصیلی مشتری، شماره به ترتیب بازشدن
UPDATE comm.service_tickets t SET company_id = d.company_id
  FROM acc.detail_accounts d WHERE d.detail_account_id = t.customer_detail_account_id AND t.company_id IS NULL;
WITH numbered AS (
    SELECT ticket_id, ROW_NUMBER() OVER (PARTITION BY company_id ORDER BY opened_at, ticket_id) AS n
      FROM comm.service_tickets WHERE ticket_no IS NULL AND company_id IS NOT NULL)
UPDATE comm.service_tickets t SET ticket_no = numbered.n
  FROM numbered WHERE numbered.ticket_id = t.ticket_id
   AND NOT EXISTS (SELECT 1 FROM comm.service_tickets x WHERE x.company_id = t.company_id AND x.ticket_no IS NOT NULL);

CREATE UNIQUE INDEX IF NOT EXISTS ux_comm_service_tickets_company_no ON comm.service_tickets (company_id, ticket_no) WHERE ticket_no IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_comm_service_tickets_crm_open ON comm.service_tickets (company_id, status_code, resolution_due_at);
