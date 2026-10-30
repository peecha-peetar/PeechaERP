-- پیچا | R362: گواهی آنالیز (COA) از بازرسی تأییدشده؛ نتایج پارامترها هنگام صدور ثابت ذخیره می‌شود
CREATE TABLE IF NOT EXISTS qms.certificates (
    certificate_id              INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                  INT           NOT NULL REFERENCES core.companies(company_id),
    certificate_no              INT           NOT NULL,
    qc_inspection_id            INT           NOT NULL REFERENCES inv.qc_inspections(qc_inspection_id),
    item_id                     INT           NOT NULL REFERENCES inv.items(item_id),
    batch_no                    VARCHAR(50),
    customer_detail_account_id  INT           REFERENCES acc.detail_accounts(detail_account_id),
    sales_document_id           BIGINT        REFERENCES comm.commercial_documents(document_id),
    issue_date                  DATE          NOT NULL,
    status_code                 VARCHAR(10)   NOT NULL DEFAULT 'ISSUED',
    snapshot                    JSONB         NOT NULL,
    notes                       VARCHAR(500),
    issued_by_user_id           INT           NOT NULL REFERENCES sec.users(user_id),
    issued_at                   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    revoked_by_user_id          INT           REFERENCES sec.users(user_id),
    revoked_at                  TIMESTAMPTZ,
    revoke_reason               VARCHAR(500),
    CONSTRAINT uq_qms_certificates_no UNIQUE (company_id, certificate_no),
    CONSTRAINT ck_qms_certificates_status CHECK (status_code IN ('ISSUED', 'REVOKED'))
);
