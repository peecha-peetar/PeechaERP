-- پیچا | خزانه‌داری: «انواعِ سند» برایِ دریافت/پرداخت — طبقِ درخواستِ
-- صریح، در فرمِ سندِ دریافت/پرداخت به‌جایِ انتخابِ آزادِ معین، از بینِ
-- این «نوع‌سند»هایِ ازپیش‌تعریف‌شده انتخاب می‌شود (مثلاً «دریافت از
-- مشتری» یا «دریافت از تامین‌کننده»)؛ هرکدام یک معین + یک تفصیلیِ اختیاریِ
-- ثابت (اگر خالی بماند، در خودِ فرمِ سند تفصیلیِ لازم پرسیده می‌شود).

CREATE TABLE treasury.document_types (
    document_type_id  INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id          INT         NOT NULL REFERENCES core.companies(company_id),
    direction            VARCHAR(10) NOT NULL CHECK (direction IN ('RECEIPT', 'PAYMENT')),
    name                 VARCHAR(150) NOT NULL,
    account_id           INT         NOT NULL REFERENCES acc.chart_of_accounts(account_id),
    detail_account_id    INT         NULL REFERENCES acc.detail_accounts(detail_account_id)
);
