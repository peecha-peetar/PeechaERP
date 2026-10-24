-- برگشت R313 (بودجه‌ریزی). اسناد خرید، حسابداری و بودجهٔ سادهٔ خرید (comm.purchase_budgets) دست نمی‌خورند.
BEGIN;
DROP SCHEMA bud CASCADE;
DELETE FROM inv.company_features WHERE feature_code IN ('BUD_ENFORCE', 'BUD_PR_COMMIT', 'BUD_SELF_APPROVAL');
DELETE FROM inv.feature_definitions WHERE feature_code IN ('BUD_ENFORCE', 'BUD_PR_COMMIT', 'BUD_SELF_APPROVAL');
DELETE FROM public.peecha_schema_migrations WHERE filename = '223_budgeting.sql';
COMMIT;
