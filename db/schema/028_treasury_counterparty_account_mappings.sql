-- پیچا | خزانه‌داری: نگاشتِ نوعِ تفصیلی <-> معینِ حساب برایِ دریافت/پرداخت.
-- طبقِ درخواستِ صریح: هر ردیف یک «نوعِ تفصیلی» (مثلاً «مشتری») را به یک
-- معینِ حساب نگاشت می‌کند — سمتِ بستانکار برایِ دریافت، سمتِ بدهکار برایِ
-- پرداخت. «نوعِ تفصیلی» یا یک گروهِ تفصیلیِ اشخاص است (acc.person_groups
-- — مشتری/تامین‌کننده/پرسنل یا هر گروهِ سفارشیِ دیگر) یا یک نوع‌بُعدِ
-- تفصیلیِ غیرِشخصی (acc.detail_dimension_types — مرکزِ هزینه/پروژه/...).

CREATE TABLE treasury.counterparty_account_mappings (
    mapping_id         INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id          INT         NOT NULL REFERENCES core.companies(company_id),
    direction            VARCHAR(10) NOT NULL CHECK (direction IN ('RECEIPT', 'PAYMENT')),
    person_group_id      INT         NULL REFERENCES acc.person_groups(person_group_id),
    dimension_type_id    INT         NULL REFERENCES acc.detail_dimension_types(dimension_type_id),
    account_id           INT         NOT NULL REFERENCES acc.chart_of_accounts(account_id),
    CONSTRAINT ck_counterparty_account_mappings_one_group CHECK (
        (person_group_id IS NOT NULL AND dimension_type_id IS NULL)
        OR (person_group_id IS NULL AND dimension_type_id IS NOT NULL)
    )
);
