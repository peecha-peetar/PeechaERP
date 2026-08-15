-- پیچا | فصلِ ۱۴: فیشِ اصلاحی (correction) باید بتواند برایِ همان
-- run_id/employee_id کنارِ فیشِ اصلی وجود داشته باشد؛ UNIQUE(run_id,
-- employee_id) فعلیِ ۰۴۵ این را کاملاً مسدود می‌کرد. به یک ایندکسِ
-- یکتایِ جزئی (فقط برایِ فیشِ اصلی، یعنی correction_of_payslip_id IS
-- NULL) تبدیل می‌شود؛ محدودیتِ «حداکثر یک فیشِ اصلی به‌ازایِ هر
-- run/employee» دست‌نخورده می‌ماند.

ALTER TABLE payroll.payslips DROP CONSTRAINT uq_payroll_payslips_run_employee;

CREATE UNIQUE INDEX uq_payroll_payslips_run_employee_original
    ON payroll.payslips (run_id, employee_id)
    WHERE correction_of_payslip_id IS NULL;
