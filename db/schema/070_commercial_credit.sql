-- پیچا | مدیریتِ بازرگانی — مرحلهٔ ۲/۵: اعتبار، بدونِ دفترِ موازی.
-- مانده/مواجههٔ اعتباری هرگز ذخیره نمی‌شود — همیشه زنده از
-- acc.journal_entry_lines محاسبه می‌شود؛ این‌جا فقط سیاست و استثنا.
-- پیش‌نیاز: 067_commercial_documents.sql

CREATE TABLE comm.credit_policies (
    policy_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    party_type_code VARCHAR(10) NOT NULL CHECK (party_type_code IN ('CUSTOMER', 'SUPPLIER')),
    default_credit_limit NUMERIC(18,2) NOT NULL DEFAULT 0,
    default_payment_term_days SMALLINT NOT NULL DEFAULT 0,
    overdue_grace_days SMALLINT NOT NULL DEFAULT 0,
    CONSTRAINT uq_comm_credit_policies UNIQUE (company_id, party_type_code)
);

CREATE TABLE comm.credit_holds (
    hold_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    party_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    related_document_id BIGINT NULL REFERENCES comm.commercial_documents(document_id),
    reason VARCHAR(500) NOT NULL,
    held_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    held_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_by_user_id INT NULL REFERENCES sec.users(user_id),
    released_at TIMESTAMPTZ NULL
);

CREATE INDEX ix_comm_credit_holds_open
    ON comm.credit_holds (party_detail_account_id)
    WHERE released_at IS NULL;
