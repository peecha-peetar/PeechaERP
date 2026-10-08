-- برگشت R295: حذف درخواست‌های مرخصی.
BEGIN;
DROP TABLE IF EXISTS hr.leave_requests;
DELETE FROM public.peecha_schema_migrations WHERE filename = '213_hr_leave_requests.sql';
COMMIT;
