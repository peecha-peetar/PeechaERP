-- برگشت دستی 206_crm_marketing.sql
BEGIN;
ALTER TABLE crm.opportunities DROP COLUMN IF EXISTS campaign_id;
ALTER TABLE crm.leads DROP COLUMN IF EXISTS campaign_id;
DROP TABLE IF EXISTS crm.campaign_members, crm.campaigns;
DELETE FROM public.peecha_schema_migrations WHERE filename = '206_crm_marketing.sql';
COMMIT;
