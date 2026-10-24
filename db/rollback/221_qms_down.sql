-- برگشت R311 (سیستم مدیریت کیفیت). بازرسی‌های بدون ردیف و بچ (فقط عملیات تولید) حذف می‌شوند چون قید قدیمی آن‌ها را نمی‌پذیرد.
-- نگه‌داشت‌های فعال کیفیت تولید و مرجوعی همان رزرو QC_HOLD هستند و با برگشت 217 آزاد می‌شوند.
BEGIN;
DROP TRIGGER IF EXISTS tr_inv_qc_inspections_lock ON inv.qc_inspections;
DROP FUNCTION IF EXISTS inv.qc_inspections_lock();
DROP SCHEMA qms CASCADE;
DELETE FROM inv.qc_inspections WHERE stock_document_line_id IS NULL AND batch_id IS NULL;
DROP INDEX IF EXISTS inv.ux_inv_qc_inspections_open_line;
DROP INDEX IF EXISTS inv.ux_inv_qc_inspections_open_operation;
DROP INDEX IF EXISTS inv.ux_inv_qc_inspections_idempotency;
DROP INDEX IF EXISTS inv.ix_inv_qc_inspections_line;
DROP INDEX IF EXISTS inv.ix_inv_qc_inspections_order;
DROP INDEX IF EXISTS inv.ix_inv_qc_inspections_status;
ALTER TABLE inv.qc_inspections
    DROP CONSTRAINT IF EXISTS ck_inv_qc_inspections_stage,
    DROP CONSTRAINT IF EXISTS ck_inv_qc_inspections_status,
    DROP CONSTRAINT IF EXISTS ck_inv_qc_inspections_disposition,
    DROP CONSTRAINT IF EXISTS ck_inv_qc_inspections_quantities,
    DROP CONSTRAINT IF EXISTS ck_inv_qc_inspections_one_target;
ALTER TABLE inv.qc_inspections
    DROP COLUMN stage_code, DROP COLUMN status_code, DROP COLUMN plan_id, DROP COLUMN lot_quantity,
    DROP COLUMN accepted_quantity, DROP COLUMN pending_quantity, DROP COLUMN disposition_code,
    DROP COLUMN production_order_id, DROP COLUMN order_operation_id, DROP COLUMN reinspection_of_id,
    DROP COLUMN approved_by_user_id, DROP COLUMN approved_at, DROP COLUMN decision_notes,
    DROP COLUMN transfer_stock_document_id, DROP COLUMN idempotency_key;
ALTER TABLE inv.qc_inspections ADD CONSTRAINT ck_inv_qc_inspections_one_target
    CHECK ((stock_document_line_id IS NOT NULL)::int + (batch_id IS NOT NULL)::int = 1);
DELETE FROM inv.company_features WHERE feature_code IN
    ('QC_SEPARATE_APPROVAL', 'QC_QUARANTINE_LOCK', 'QC_PRODUCTION', 'QC_SALES_RETURN', 'QC_ROLE_PERMISSIONS');
DELETE FROM inv.feature_definitions WHERE feature_code IN
    ('QC_SEPARATE_APPROVAL', 'QC_QUARANTINE_LOCK', 'QC_PRODUCTION', 'QC_SALES_RETURN', 'QC_ROLE_PERMISSIONS');
DELETE FROM public.peecha_schema_migrations WHERE filename = '221_qms.sql';
COMMIT;
