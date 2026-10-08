-- برگشت دستی 207_crm_service.sql (ستون‌های افزوده از تیکت حذف می‌شوند؛ تیکت‌ها باقی می‌مانند)
BEGIN;
DROP INDEX IF EXISTS comm.ux_comm_service_tickets_company_no;
DROP INDEX IF EXISTS comm.ix_comm_service_tickets_crm_open;
ALTER TABLE comm.service_tickets
    DROP CONSTRAINT IF EXISTS ck_comm_service_tickets_crm_type,
    DROP CONSTRAINT IF EXISTS ck_comm_service_tickets_crm_priority,
    DROP CONSTRAINT IF EXISTS ck_comm_service_tickets_crm_satisfaction,
    DROP COLUMN IF EXISTS company_id, DROP COLUMN IF EXISTS ticket_no, DROP COLUMN IF EXISTS ticket_type,
    DROP COLUMN IF EXISTS priority_code, DROP COLUMN IF EXISTS channel_code, DROP COLUMN IF EXISTS category,
    DROP COLUMN IF EXISTS related_document_id, DROP COLUMN IF EXISTS sla_policy_id, DROP COLUMN IF EXISTS first_response_due_at,
    DROP COLUMN IF EXISTS resolution_due_at, DROP COLUMN IF EXISTS first_responded_at, DROP COLUMN IF EXISTS resolved_at,
    DROP COLUMN IF EXISTS sla_breached, DROP COLUMN IF EXISTS escalation_level, DROP COLUMN IF EXISTS escalated_at,
    DROP COLUMN IF EXISTS resolution_text, DROP COLUMN IF EXISTS satisfaction_score, DROP COLUMN IF EXISTS satisfaction_comment,
    DROP COLUMN IF EXISTS created_by_user_id, DROP COLUMN IF EXISTS updated_at;
DROP TABLE IF EXISTS crm.sla_policies;
DELETE FROM public.peecha_schema_migrations WHERE filename = '207_crm_service.sql';
COMMIT;
