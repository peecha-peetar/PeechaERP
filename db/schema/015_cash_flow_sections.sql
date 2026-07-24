-- پیچا | طبقه‌بندیِ حساب‌ها از نقطه‌نظرِ صورتِ گردشِ وجوهِ نقد (عملیاتی/
-- سرمایه‌گذاری/تامینِ مالی) — پیش‌نیازِ گزارشِ «گردشِ وجوهِ نقدِ غیرمستقیم».
-- پیش‌نیاز: 003_accounting_core.sql

CREATE TABLE acc.cash_flow_sections (
    cash_flow_section_id SMALLINT    NOT NULL PRIMARY KEY,
    code                  VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO acc.cash_flow_sections (cash_flow_section_id, code) VALUES
    (1, 'OPERATING'), (2, 'INVESTING'), (3, 'FINANCING');

-- طبقِ درخواستِ صریح: برخلافِ ماهیت/دسته/نوعِ حساب (که اجباری‌اند)، این
-- یکی nullable است — فقط حساب‌هایِ ترازنامه‌ایِ غیرِنقدی (نه خودِ صندوق/
-- بانک، نه درآمد/هزینه که در سودِ خالص از قبل حساب شده‌اند) به این
-- طبقه‌بندی نیاز دارند؛ NULL یعنی «در گردشِ نقدِ غیرمستقیم دیده نمی‌شود».
ALTER TABLE acc.chart_of_accounts
    ADD COLUMN cash_flow_section_id SMALLINT NULL REFERENCES acc.cash_flow_sections(cash_flow_section_id);
