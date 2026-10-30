-- برگشت R304: حذف کلیدهای اسکن و کارتابل جانمایی.
BEGIN;
DELETE FROM inv.company_features WHERE feature_code IN ('WMS_SCAN_CONFIRMATION', 'WMS_PUTAWAY_IN_CARTABLE');
DELETE FROM inv.feature_definitions WHERE feature_code IN ('WMS_SCAN_CONFIRMATION', 'WMS_PUTAWAY_IN_CARTABLE');
DELETE FROM public.peecha_schema_migrations WHERE filename = '215_wms_scan_putaway.sql';
COMMIT;
