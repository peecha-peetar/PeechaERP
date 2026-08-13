-- پیچا | آیتمِ ۵ («صورتِ گردشِ وجوهِ نقد استاندارد نیست») — گسترشِ سه‌
-- بخشیِ فعلی (عملیاتی/سرمایه‌گذاری/تامینِ مالی، الگویِ ساده‌شده‌یِ IFRS)
-- به پنج طبقه‌یِ استانداردِ حسابداریِ ایران (استانداردِ شماره‌یِ ۲):
-- ۱) فعالیت‌هایِ عملیاتی، ۲) بازده‌یِ سرمایه‌گذاری‌ها و سودِ پرداختی بابتِ
-- تامینِ مالی، ۳) مالیات بر درآمد، ۴) فعالیت‌هایِ سرمایه‌گذاری،
-- ۵) فعالیت‌هایِ تامینِ مالی.
-- پیش‌نیاز: 015_cash_flow_sections.sql

-- کدِ «بازده‌یِ سرمایه‌گذاری‌ها و سودِ پرداختیِ تامینِ مالی» از حدِ فعلیِ
-- ستونِ code (varchar(20)) بلندتر است.
ALTER TABLE acc.cash_flow_sections ALTER COLUMN code TYPE VARCHAR(40);

INSERT INTO acc.cash_flow_sections (cash_flow_section_id, code) VALUES
    (4, 'INVESTMENT_RETURNS_FINANCE_COST'),
    (5, 'INCOME_TAX')
ON CONFLICT (cash_flow_section_id) DO NOTHING;
