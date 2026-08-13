-- پیچا | طبقِ درخواستِ صریح («در گزارشِ ترازنامه دو ستونِ چپ/راست داشته
-- باشیم و در تنظیمات مشخص کنیم کدام گروه در کدام سمت باشد») — سمتِ
-- نمایشِ هر گروهِ حسابِ سطحِ ۱ در ترازنامه. هم‌الگو با acc.cash_flow_sections:
-- یک جدولِ کوچکِ دوعضوی + یک ستونِ nullable رویِ chart_of_accounts. NULL
-- یعنی «خودکار» — سمت از رویِ category_code تعیین می‌شود (دارایی=راست،
-- بدهی/حقوقِ‌صاحبانِ‌سهام=چپ) تا شرکت‌هایِ موجود بدونِ پیکربندیِ اضافه هم
-- درست کار کنند.
CREATE TABLE acc.balance_sheet_sides (
    balance_sheet_side_id SMALLINT   NOT NULL PRIMARY KEY,
    code                   VARCHAR(10) NOT NULL UNIQUE
);
INSERT INTO acc.balance_sheet_sides (balance_sheet_side_id, code) VALUES
    (1, 'RIGHT'), (2, 'LEFT');

ALTER TABLE acc.chart_of_accounts
    ADD COLUMN balance_sheet_side_id SMALLINT NULL REFERENCES acc.balance_sheet_sides(balance_sheet_side_id);
