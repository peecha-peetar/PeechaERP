-- برگشت دستی 204_crm_core.sql (اجرا فقط با تصمیم مدیر سیستم؛ دادهٔ CRM حذف می‌شود).
-- فعالیت‌های بدون مشتری (فعالیت سرنخ) و نوع‌های تازه پیش از بازگرداندن CHECKها حذف می‌شوند.
BEGIN;
DELETE FROM comm.customer_activities WHERE customer_detail_account_id IS NULL
    OR activity_type_code NOT IN ('COMPLAINT', 'MEETING', 'OPPORTUNITY', 'TASK');
ALTER TABLE comm.customer_activities DROP CONSTRAINT IF EXISTS ck_customer_activities_party;
ALTER TABLE comm.customer_activities DROP CONSTRAINT IF EXISTS ck_customer_activities_priority;
ALTER TABLE comm.customer_activities DROP CONSTRAINT IF EXISTS customer_activities_activity_type_code_check;
ALTER TABLE comm.customer_activities ADD CONSTRAINT customer_activities_activity_type_code_check
    CHECK (activity_type_code IN ('COMPLAINT', 'MEETING', 'OPPORTUNITY', 'TASK'));
ALTER TABLE comm.customer_activities
    DROP COLUMN IF EXISTS lead_id, DROP COLUMN IF EXISTS opportunity_id, DROP COLUMN IF EXISTS ticket_id,
    DROP COLUMN IF EXISTS customer_visit_id, DROP COLUMN IF EXISTS start_at, DROP COLUMN IF EXISTS duration_minutes,
    DROP COLUMN IF EXISTS priority_code, DROP COLUMN IF EXISTS result_text, DROP COLUMN IF EXISTS next_action,
    DROP COLUMN IF EXISTS next_action_date, DROP COLUMN IF EXISTS updated_at;
ALTER TABLE comm.customer_activities ALTER COLUMN customer_detail_account_id SET NOT NULL;
DROP TABLE IF EXISTS crm.opportunity_documents, crm.opportunity_lines;
ALTER TABLE crm.leads DROP CONSTRAINT IF EXISTS fk_crm_leads_opportunity;
DROP TABLE IF EXISTS crm.opportunities, crm.leads, crm.pipeline_stages, crm.pipelines, crm.lead_sources;
DELETE FROM public.peecha_schema_migrations WHERE filename = '204_crm_core.sql';
COMMIT;
