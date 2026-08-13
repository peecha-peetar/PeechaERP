-- پیچا | فصلِ ۱۶: صدورِ خودکارِ سندِ حسابداریِ حقوق نیاز به یک حسابِ
-- هزینهٔ جداگانه برایِ سهمِ کارفرمایِ بیمه دارد (طبقِ ساختارِ سندِ
-- نمونهٔ سند: «هزینهٔ سهمِ کارفرمای بیمه، بدهکار»)؛ هیچ فیلدِ موجودی
-- این را پوشش نمی‌داد.

ALTER TABLE payroll.insurance_configs
    ADD COLUMN employer_expense_gl_account_id INT REFERENCES acc.chart_of_accounts(account_id);
