-- برگشت R309: حذف کلیدهای انتقال دومرحله‌ای، پیشنهاد چیدمان و ارسال مستقیم (اسناد ثبت‌شده دست نمی‌خورند).
BEGIN;
DELETE FROM inv.company_features WHERE feature_code IN ('WMS_TWO_STEP_TRANSFER', 'WMS_SLOTTING_SUGGESTIONS', 'WMS_CROSS_DOCK');
DELETE FROM inv.feature_definitions WHERE feature_code IN ('WMS_TWO_STEP_TRANSFER', 'WMS_SLOTTING_SUGGESTIONS', 'WMS_CROSS_DOCK');
DELETE FROM public.peecha_schema_migrations WHERE filename = '220_wms_flow.sql';
COMMIT;
