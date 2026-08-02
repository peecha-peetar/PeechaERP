-- بانک‌هایِ مرجع (نامِ بانکِ صادرکننده‌یِ چکِ دریافتی) + فیلدهایِ تکمیلیِ
-- چکِ دریافتی (سریال/شبا/شماره‌حساب/کدِملی و تلفنِ صاحبِ چک) — طبقِ
-- درخواستِ صریح: «نام بانک اگر لیستی باشه ... در فرمی جدا تعریف بشه بهتره».

CREATE TABLE treasury.banks (
    bank_id      INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id   INT          NOT NULL REFERENCES core.companies(company_id),
    code         VARCHAR(20)  NULL,
    name         VARCHAR(150) NOT NULL,
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_treasury_banks_name UNIQUE (company_id, name)
);

ALTER TABLE treasury.received_checks
    ADD COLUMN check_serial      VARCHAR(30)  NULL,
    ADD COLUMN iban               VARCHAR(34)  NULL,
    ADD COLUMN bank_account_no    VARCHAR(40)  NULL,
    ADD COLUMN drawer_national_id VARCHAR(15)  NULL,
    ADD COLUMN drawer_phone       VARCHAR(20)  NULL,
    ADD COLUMN bank_id            INT          NULL REFERENCES treasury.banks(bank_id);
