-- طبقِ درخواستِ صریح («هر دریافت و پرداخت رفرنسِ فاکتور را داشته باشد و
-- مدیریتِ تسویه‌یِ فاکتورها را ایجاد کن»): جدولِ تخصیصِ دریافت/پرداخت به
-- فاکتور -- چون هر رسیدِ خزانه‌داری در این برنامه چیزی جز یک سندِ
-- حسابداری (acc.journal_entries) نیست (هیچ جدولِ «سندِ خزانه‌داری»یِ
-- جداگانه‌ای وجود ندارد)، تخصیص مستقیماً به journal_entry_id وصل می‌شود.
-- یک فاکتور می‌تواند چند تخصیص داشته باشد (تسویه‌یِ جزئی/اقساطی)، و یک
-- سندِ دریافت/پرداخت هم می‌تواند بینِ چند فاکتور تقسیم شود.
CREATE TABLE comm.invoice_settlements (
    settlement_id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES core.companies(company_id),
    invoice_document_id BIGINT NOT NULL REFERENCES comm.commercial_documents(document_id),
    journal_entry_id BIGINT NULL REFERENCES acc.journal_entries(journal_entry_id),
    settlement_date DATE NOT NULL,
    amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    reference_no VARCHAR(100) NULL,
    description VARCHAR(500) NULL,
    created_by_user_id BIGINT NOT NULL REFERENCES sec.users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_invoice_settlements_invoice ON comm.invoice_settlements (invoice_document_id);
CREATE INDEX ix_invoice_settlements_je ON comm.invoice_settlements (journal_entry_id);
CREATE INDEX ix_invoice_settlements_company ON comm.invoice_settlements (company_id);
