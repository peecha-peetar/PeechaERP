-- پیچا R308 — انبار پیشرفته، فاز ۷: شاخص‌های تکمیلی عملیات انبار (پیش‌فرض خاموش) و ایندکس داشبورد.
-- برگشت: db/rollback/219_wms_kpis_down.sql

INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('WMS_ADVANCED_KPIS', 'شاخص‌های تکمیلی عملیات انبار', 'WMS', NULL,
     'در داشبورد عملیات انبار این شاخص‌ها هم از روی داده‌های ثبت‌شده نشان داده می‌شوند: سهم وظایفی که با اسکن تایید شده‌اند، برداشت‌های کسری و علت‌هایشان، فاصلهٔ رسید تا جانمایی، نتیجه و زمان انتظار کنترل کیفیت، و بچ‌های منقضی و نزدیک به انقضا.')
ON CONFLICT (feature_code) DO NOTHING;

CREATE INDEX IF NOT EXISTS ix_inv_warehouse_tasks_done ON inv.warehouse_tasks (company_id, completed_at) WHERE status_code = 'DONE';
CREATE INDEX IF NOT EXISTS ix_inv_qc_inspections_date ON inv.qc_inspections (company_id, inspected_at);
