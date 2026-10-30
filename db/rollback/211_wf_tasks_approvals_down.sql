-- برگشت R292: حذف جدول‌های کار/تایید موتور گردش کار و ستون کاربر کارمند.
BEGIN;
DROP INDEX IF EXISTS hr.ux_hr_employees_user;
ALTER TABLE hr.employees DROP COLUMN IF EXISTS user_id;
DROP TABLE IF EXISTS wf.delegations;
DROP TABLE IF EXISTS wf.task_decisions;
DROP TABLE IF EXISTS wf.task_assignees;
DROP TABLE IF EXISTS wf.tasks;
DELETE FROM public.peecha_schema_migrations WHERE filename = '211_wf_tasks_approvals.sql';
COMMIT;
