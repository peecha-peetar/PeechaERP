-- پیچا | R348: سامانهٔ مودیان (صورتحساب الکترونیکی)
-- پیش‌نیاز: comm.commercial_documents، 235_moadian_item_codes.sql

CREATE TABLE IF NOT EXISTS comm.moadian_settings (
    company_id           INT PRIMARY KEY REFERENCES core.companies(company_id),
    memory_id            VARCHAR(6)   NULL,     -- شناسهٔ یکتای حافظهٔ مالیاتی
    seller_tin           VARCHAR(14)  NULL,     -- شمارهٔ اقتصادی فروشنده
    branch_code          VARCHAR(10)  NULL,
    api_url              VARCHAR(200) NULL,
    credentials_encrypted BYTEA       NULL,     -- کلید خصوصی و گواهی (رمزشده)
    last_serial          BIGINT       NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS comm.moadian_invoices (
    moadian_invoice_id   BIGSERIAL PRIMARY KEY,
    company_id           INT          NOT NULL REFERENCES core.companies(company_id),
    document_id          BIGINT       NOT NULL REFERENCES comm.commercial_documents(document_id),
    subject_code         SMALLINT     NOT NULL,  -- ۱ اصلی، ۲ اصلاحی، ۳ ابطالی، ۴ برگشت از فروش
    serial               BIGINT       NOT NULL,
    tax_id               VARCHAR(22)  NOT NULL UNIQUE,
    related_tax_id       VARCHAR(22)  NULL,
    payload              JSONB        NOT NULL,
    status               VARCHAR(15)  NOT NULL DEFAULT 'PREPARED',  -- PREPARED|SENT|SUCCESS|FAILED
    uid                  VARCHAR(40)  NULL,
    reference_number     VARCHAR(60)  NULL,
    errors               JSONB        NULL,
    created_by_user_id   INT          NULL REFERENCES sec.users(user_id),
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    sent_at              TIMESTAMPTZ  NULL,
    checked_at           TIMESTAMPTZ  NULL,
    CONSTRAINT ck_moadian_invoice_status CHECK (status IN ('PREPARED', 'SENT', 'SUCCESS', 'FAILED')),
    CONSTRAINT ck_moadian_invoice_subject CHECK (subject_code BETWEEN 1 AND 4)
);
CREATE INDEX IF NOT EXISTS ix_moadian_invoices_document ON comm.moadian_invoices(document_id);
