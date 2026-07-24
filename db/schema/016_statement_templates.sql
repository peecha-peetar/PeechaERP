-- پیچا | طراحِ گزارشِ سفارشی (فازِ ۲): الگوهایِ صورتِ مالی که هر ردیفشان
-- می‌تواند از جمعِ چند حساب (در هر سطحی: گروه/کل/معین، با علامتِ +/−) یا
-- از جمعِ چند ردیفِ دیگرِ همان الگو (فرمول/زیرکل) ساخته شود.
-- پیش‌نیاز: 003_accounting_core.sql

CREATE TABLE acc.statement_templates (
    template_id     SERIAL      NOT NULL PRIMARY KEY,
    company_id      INT         NOT NULL REFERENCES core.companies(company_id),
    name            VARCHAR(200) NOT NULL,
    statement_type  VARCHAR(20) NOT NULL
        CHECK (statement_type IN ('INCOME_STATEMENT', 'BALANCE_SHEET', 'CASH_FLOW', 'CUSTOM')),
    display_order   INT         NOT NULL DEFAULT 0
);

CREATE TABLE acc.statement_rows (
    row_id       SERIAL      NOT NULL PRIMARY KEY,
    template_id  INT         NOT NULL REFERENCES acc.statement_templates(template_id) ON DELETE CASCADE,
    row_order    INT         NOT NULL,
    label        VARCHAR(300) NOT NULL,
    row_type     VARCHAR(20) NOT NULL CHECK (row_type IN ('HEADER', 'ACCOUNTS', 'FORMULA')),
    indent_level SMALLINT    NOT NULL DEFAULT 0,
    is_bold      BOOLEAN     NOT NULL DEFAULT FALSE
);
CREATE INDEX ix_statement_rows_template ON acc.statement_rows(template_id);

-- اجزایِ یک ردیفِ ACCOUNTS — account_id می‌تواند در هر سطحی باشد (گروه/کل/
-- معین)، چون reports.py::compute_account_balances از قبل برایِ همه‌یِ
-- سطوح رول‌آپ دارد.
CREATE TABLE acc.statement_row_accounts (
    row_id     INT NOT NULL REFERENCES acc.statement_rows(row_id) ON DELETE CASCADE,
    account_id INT NOT NULL REFERENCES acc.chart_of_accounts(account_id),
    sign       SMALLINT NOT NULL CHECK (sign IN (1, -1)),
    PRIMARY KEY (row_id, account_id)
);

-- اجزایِ یک ردیفِ FORMULA — ارجاع به ردیف‌هایِ دیگرِ همان الگو.
CREATE TABLE acc.statement_row_refs (
    row_id     INT NOT NULL REFERENCES acc.statement_rows(row_id) ON DELETE CASCADE,
    ref_row_id INT NOT NULL REFERENCES acc.statement_rows(row_id) ON DELETE CASCADE,
    sign       SMALLINT NOT NULL CHECK (sign IN (1, -1)),
    PRIMARY KEY (row_id, ref_row_id)
);
