-- برگشت R305: حذف کلید کنترل برداشت.
BEGIN;
DELETE FROM inv.company_features WHERE feature_code = 'WMS_PICK_CONTROL';
DELETE FROM inv.feature_definitions WHERE feature_code = 'WMS_PICK_CONTROL';
DELETE FROM public.peecha_schema_migrations WHERE filename = '216_wms_pick_control.sql';
COMMIT;
