-- پیچا R305 — انبار پیشرفته، فاز ۴: کنترل برداشت (پیش‌فرض خاموش). برگشت: db/rollback/216_wms_pick_control_down.sql

INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('WMS_PICK_CONTROL', 'کنترل برداشت و آماده‌سازی سفارش', 'WMS', NULL,
     'برداشت بیش از مقدار وظیفه ممکن نیست و برداشت کمتر علت می‌خواهد. محل برداشت از محلی پیشنهاد می‌شود که موجودی آزاد دارد و زودانقضاتر است (محل رزرو سفارش اولویت دارد). ساخت موج برداشت، وظایف سفارش‌های فروش رزروشده را هم خودکار می‌سازد.')
ON CONFLICT (feature_code) DO NOTHING;
