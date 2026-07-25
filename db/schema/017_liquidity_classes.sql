-- پیچا | طبقه‌بندیِ حساب‌ها از نقطه‌نظرِ نقدینگی (جاری/غیرِجاری/موجودی) —
-- پیش‌نیازِ نسبت‌هایِ جاری/آنی در گزارشِ «نسبت‌هایِ مالی».
-- پیش‌نیاز: 003_accounting_core.sql

CREATE TABLE acc.liquidity_classes (
    liquidity_class_id SMALLINT    NOT NULL PRIMARY KEY,
    code                VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO acc.liquidity_classes (liquidity_class_id, code) VALUES
    (1, 'CURRENT'), (2, 'CURRENT_INVENTORY'), (3, 'NON_CURRENT');

-- طبقِ همان الگویِ cash_flow_section (015): nullable — فقط حساب‌هایِ
-- دارایی/بدهی که کاربر خواسته در نسبتِ جاری/آنی دیده شوند طبقه‌بندی
-- می‌شوند؛ NULL یعنی «در نسبتِ جاری/آنی حساب نمی‌شود». CURRENT_INVENTORY
-- زیرمجموعه‌یِ CURRENT است (در دارایی‌هایِ جاری جمع می‌شود) ولی از
-- دارایی‌هایِ آنی (Quick Assets) کم می‌شود.
ALTER TABLE acc.chart_of_accounts
    ADD COLUMN liquidity_class_id SMALLINT NULL REFERENCES acc.liquidity_classes(liquidity_class_id);
