-- پیچا | خزانه‌داری: نگاشتِ «انواعِ طرفِ‌حساب» برایِ دریافت/پرداخت.
-- طبقِ درخواستِ صریح: «دریافت از تامین‌کننده یک رفتار داشته باشه، دریافت
-- از مشتری یک رفتارِ دیگه، دریافتِ درآمد یک رفتارِ دیگه» — یعنی برایِ هر
-- جهت (دریافت/پرداخت) و هر گروهِ تفصیلی (مثلاً تامین‌کننده/مشتری/پرسنل یا
-- هر گروهِ تفصیلیِ دیگرِ تعریف‌شده)، یک معینِ مشخص تنظیم می‌شود؛ اختیاری
-- می‌توان یک تفصیلیِ ثابت هم هارد‌کد کرد (اگر خالی بماند، در فرمِ سند از
-- بینِ همه‌یِ تفصیلی‌هایِ همان گروه انتخاب می‌شود).

CREATE TABLE treasury.counterparty_mappings (
    mapping_id         INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id          INT        NOT NULL REFERENCES core.companies(company_id),
    direction            VARCHAR(10) NOT NULL CHECK (direction IN ('RECEIPT', 'PAYMENT')),
    dimension_type_id    SMALLINT   NOT NULL REFERENCES acc.detail_dimension_types(dimension_type_id),
    person_group_id      SMALLINT   NOT NULL DEFAULT 0,
    account_id           INT        NOT NULL REFERENCES acc.chart_of_accounts(account_id),
    detail_account_id    INT        NULL REFERENCES acc.detail_accounts(detail_account_id),
    CONSTRAINT uq_treasury_counterparty_mappings UNIQUE (company_id, direction, dimension_type_id, person_group_id)
);
