-- پیچا | R345: درآمد مشمول مالیات هر فیش، تا بازمحاسبهٔ همان اجرا سهم قبلی‌اش را از دفتر مالیات سالانه بردارد
-- (بدون آن، هر بازمحاسبه مالیات ماه را دوبار در دفتر تجمعی حساب می‌کرد).
-- پیش‌نیاز: 044_payroll_core.sql

ALTER TABLE payroll.payslips ADD COLUMN IF NOT EXISTS taxable_income NUMERIC(18, 2) NULL;
