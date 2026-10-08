-- برگشت R291: حذف جدول‌های هستهٔ موتور گردش کار (جدول‌های کارتابل قدیمی wf.* حفظ می‌شوند).
BEGIN;
DROP TABLE IF EXISTS wf.settings;
ALTER TABLE audit.activity_log DROP CONSTRAINT IF EXISTS ck_activity_log_action;
ALTER TABLE audit.activity_log ADD CONSTRAINT ck_activity_log_action
    CHECK (action IN ('CREATE', 'UPDATE', 'DELETE', 'APPROVE', 'REVERSE', 'MERGE')) NOT VALID;
DROP TABLE IF EXISTS wf.timers;
DROP TABLE IF EXISTS wf.exceptions;
DROP TABLE IF EXISTS wf.action_executions;
DROP TABLE IF EXISTS wf.instance_steps;
DROP TABLE IF EXISTS wf.instances;
DROP TABLE IF EXISTS wf.events;
DROP TABLE IF EXISTS wf.definition_triggers;
ALTER TABLE IF EXISTS wf.definitions DROP CONSTRAINT IF EXISTS fk_wf_definitions_active_version;
DROP TABLE IF EXISTS wf.definition_versions;
DROP TABLE IF EXISTS wf.definitions;
DELETE FROM public.peecha_schema_migrations WHERE filename = '210_wf_engine_core.sql';
COMMIT;
