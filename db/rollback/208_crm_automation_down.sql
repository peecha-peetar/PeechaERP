-- برگشت دستی 208_crm_automation.sql
BEGIN;
DROP TABLE IF EXISTS crm.automation_log, crm.automation_rules, crm.messages, crm.message_templates;
DELETE FROM public.peecha_schema_migrations WHERE filename = '208_crm_automation.sql';
COMMIT;
