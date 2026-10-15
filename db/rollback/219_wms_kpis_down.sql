-- برگشت R308: حذف کلید شاخص‌های تکمیلی و ایندکس‌های داشبورد.
BEGIN;
DROP INDEX IF EXISTS inv.ix_inv_warehouse_tasks_done;
DROP INDEX IF EXISTS inv.ix_inv_qc_inspections_date;
DELETE FROM inv.company_features WHERE feature_code = 'WMS_ADVANCED_KPIS';
DELETE FROM inv.feature_definitions WHERE feature_code = 'WMS_ADVANCED_KPIS';
DELETE FROM public.peecha_schema_migrations WHERE filename = '219_wms_kpis.sql';
COMMIT;
