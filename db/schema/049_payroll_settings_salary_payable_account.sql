-- پیچا | فصلِ ۱۶: ردیفِ بستانکارِ «حقوقِ پرداختنی/بانک» (خالص پرداختنی)
-- در سندِ خودکار نیاز به یک حسابِ ثابت در سطحِ شرکت دارد؛ هیچ pay_item یا
-- تنظیماتِ دیگری معادلِ این نبود.

ALTER TABLE payroll.company_settings
    ADD COLUMN salary_payable_gl_account_id INT REFERENCES acc.chart_of_accounts(account_id);
