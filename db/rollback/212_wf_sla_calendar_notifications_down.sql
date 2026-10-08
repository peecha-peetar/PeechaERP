-- برگشت R293: حذف تعهد زمانی، تعطیلات و ترجیحات اعلان.
BEGIN;
DROP INDEX IF EXISTS sec.ix_sec_notifications_unread;
ALTER TABLE sec.notifications DROP COLUMN IF EXISTS channels;
ALTER TABLE sec.notifications DROP COLUMN IF EXISTS read_at;
ALTER TABLE sec.notifications DROP COLUMN IF EXISTS priority_code;
DROP TABLE IF EXISTS sec.notification_preferences;
DELETE FROM wf.task_decisions WHERE decision = 'ESCALATE';
ALTER TABLE wf.task_decisions DROP CONSTRAINT IF EXISTS ck_wf_task_decisions_decision;
ALTER TABLE wf.task_decisions ADD CONSTRAINT task_decisions_decision_check CHECK (decision IN
    ('APPROVE', 'REJECT', 'CHANGES', 'DONE', 'COMMENT', 'DELEGATE', 'REASSIGN', 'CANCEL'));
DROP INDEX IF EXISTS wf.ix_wf_tasks_sla;
ALTER TABLE wf.tasks DROP CONSTRAINT IF EXISTS ck_wf_tasks_sla_status;
ALTER TABLE wf.tasks DROP COLUMN IF EXISTS sla_status;
ALTER TABLE wf.tasks DROP COLUMN IF EXISTS escalation_level;
ALTER TABLE wf.tasks DROP COLUMN IF EXISTS escalate_at;
ALTER TABLE wf.tasks DROP COLUMN IF EXISTS warn_at;
ALTER TABLE wf.tasks DROP COLUMN IF EXISTS sla_policy_id;
DROP TABLE IF EXISTS wf.holidays;
DROP TABLE IF EXISTS wf.sla_policies;
DELETE FROM public.peecha_schema_migrations WHERE filename = '212_wf_sla_calendar_notifications.sql';
COMMIT;
