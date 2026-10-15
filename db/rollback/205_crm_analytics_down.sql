-- برگشت دستی 205_crm_analytics.sql
BEGIN;
DROP INDEX IF EXISTS comm.ix_comm_docs_crm_customer_sales;
DROP TABLE IF EXISTS crm.customer_scores, crm.segments, crm.settings;
DELETE FROM public.peecha_schema_migrations WHERE filename = '205_crm_analytics.sql';
COMMIT;
