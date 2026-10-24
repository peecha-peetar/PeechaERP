-- پیچا R303 — انبار پیشرفته، فاز ۱: کلیدهای روشن/خاموش کنترل‌های انبار + جلوگیری از وظیفهٔ انبار تکراری.
-- همهٔ کلیدها پیش‌فرض خاموش‌اند (رفتار قبلی). هیچ داده‌ای حذف یا تغییر نمی‌شود.
-- برگشت: db/rollback/214_wms_foundation_down.sql

INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('WMS_ENFORCE_RESERVATION', 'خروج فقط از موجودی آزاد (رعایت رزرو)', 'WMS', NULL,
     'حواله، انتقال و برگشت به تامین‌کننده کالایی را که برای سفارش، برداشت یا تولید رزرو شده خارج نمی‌کند؛ رزرو خود همان سند آزاد می‌شود. اصلاح موجودی (شمارش) مستثناست و فروش موبایل رد نمی‌شود، فقط هشدار ثبت می‌شود.'),
    ('WMS_SALES_ORDER_RESERVATION', 'رزرو موجودی برای سفارش فروش', 'WMS', NULL,
     'با تایید سفارش فروش، موجودی آزاد انبار برای آن رزرو می‌شود؛ با حواله یا فاکتور مصرف و با لغو یا بازگشت به پیش‌نویس آزاد می‌شود. کمبود موجودی مانع ثبت سفارش نیست.'),
    ('WMS_LOCATION_STATUS_CONTROL', 'کنترل وضعیت محل در همهٔ اسناد', 'WMS', NULL,
     'ورود به محل غیرفعال، مسدود، در حال تعمیر یا پر و خروج از محل مسدود، در حال تعمیر یا قرنطینه در همهٔ مسیرها (دسکتاپ، موبایل، تولید و فروش) رد می‌شود. از محل قرنطینه فقط برگشت به تامین‌کننده یا انتقال به انبار ضایعات/قرنطینه مجاز است. اصلاح موجودی مستثناست.'),
    ('WMS_BLOCK_EXPIRED_ISSUE', 'جلوگیری از خروج کالای منقضی', 'WMS', NULL,
     'بچ تاریخ‌گذشته در حواله و انتقال به انبار دیگر انتخاب نمی‌شود و انتخاب دستی آن هم رد می‌شود. برگشت به تامین‌کننده، انتقال به انبار ضایعات/قرنطینه و اصلاح موجودی مجاز است. فروش موبایل فقط هشدار می‌گیرد.'),
    ('WMS_ENFORCE_WAREHOUSE_ACCESS', 'اجرای دسترسی کاربران به انبار', 'WMS', 'WAREHOUSE_ACCESS_CONTROL',
     'اگر برای انباری کاربر مجاز تعریف شده باشد، فقط همان کاربران (طبق اجازهٔ رسید، حواله یا اصلاح) سند آن انبار را ثبت می‌کنند و موجودی آن را در موبایل می‌بینند. انبار بدون فهرست کاربر برای همه آزاد است و مدیر کل سیستم همیشه مجاز است.'),
    ('WMS_DETAILED_MOBILE_PERMISSIONS', 'دسترسی جداگانه برای عملیات انبار در موبایل', 'WMS', NULL,
     'علاوه بر دسترسی «نقشه و محل‌های انبار»، وظایف، موج و شمارش در موبایل دسترسی «جانمایی، برداشت و برنامهٔ شمارش» و انتقال در موبایل دسترسی «انتقال» را لازم دارد.')
ON CONFLICT (feature_code) DO NOTHING;

-- یک وظیفهٔ باز/انجام‌شده برای هر ردیف منبع (همان قاعدهٔ generate_tasks، حالا در دیتابیس).
-- اگر از قبل وظیفهٔ تکراری وجود داشته باشد، ایندکس ساخته نمی‌شود و هیچ داده‌ای حذف نمی‌شود.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM inv.warehouse_tasks
        WHERE status_code <> 'CANCELLED' AND source_stock_line_id IS NOT NULL
        GROUP BY task_type_code, source_stock_line_id HAVING count(*) > 1
    ) THEN
        CREATE UNIQUE INDEX IF NOT EXISTS ux_inv_warehouse_tasks_stock_line
            ON inv.warehouse_tasks (task_type_code, source_stock_line_id)
            WHERE status_code <> 'CANCELLED' AND source_stock_line_id IS NOT NULL;
    ELSE
        RAISE NOTICE 'R303: duplicate warehouse tasks per stock line exist; unique index skipped';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM inv.warehouse_tasks
        WHERE status_code <> 'CANCELLED' AND source_commercial_line_id IS NOT NULL
        GROUP BY task_type_code, source_commercial_line_id HAVING count(*) > 1
    ) THEN
        CREATE UNIQUE INDEX IF NOT EXISTS ux_inv_warehouse_tasks_comm_line
            ON inv.warehouse_tasks (task_type_code, source_commercial_line_id)
            WHERE status_code <> 'CANCELLED' AND source_commercial_line_id IS NOT NULL;
    ELSE
        RAISE NOTICE 'R303: duplicate warehouse tasks per commercial line exist; unique index skipped';
    END IF;
END $$;

-- توضیح ساده برای همهٔ قابلیت‌های انبار (زیر هر کلید در تنظیمات نمایش داده می‌شود)
UPDATE inv.feature_definitions SET description = v.d FROM (VALUES
    ('QUALITY_CONTROL', 'رسید کالاهایی که کنترل کیفیت لازم دارند ابتدا «در انتظار بازرسی» ثبت می‌شود.'),
    ('BATCH_TRACKING', 'شمارهٔ بچ در فرم کالا، رسید و حواله.'),
    ('EXPIRY_TRACKING', 'تاریخ تولید و انقضا برای هر بچ.'),
    ('FEFO_ALLOCATION', 'هنگام خروج، بچی که زودتر منقضی می‌شود اول پیشنهاد می‌شود.'),
    ('FULL_TRACEABILITY', 'بازرسی کیفیت برای هر رسید الزامی می‌شود (مناسب دارو و مواد غذایی).'),
    ('SERIAL_TRACKING', 'شمارهٔ سریال و اسکن آن در فرم کالا، رسید و حواله.'),
    ('WARRANTY_TRACKING', 'تاریخ پایان گارانتی برای هر سریال.'),
    ('VARIANTS', 'ساخت متغیرهای کالا (مثل رنگ و اندازه) از روی ویژگی‌ها.'),
    ('LOGISTICS_DIMENSIONS', 'وزن و حجم در فرم کالا.'),
    ('TEMPERATURE_CONTROL', 'دمای مجاز در فرم انبار.'),
    ('PROJECT_WAREHOUSES', 'امکان تعریف انبار مخصوص پروژه.'),
    ('NEW_ITEM_APPROVAL', 'کالای تازه‌ای که کسی غیر از مدیر کالا ثبت کند، برای تایید به کارتابل می‌رود.'),
    ('DOCUMENT_APPROVAL_WORKFLOW', 'ثبت نهایی سند انبار به تایید نفر دوم نیاز دارد.'),
    ('BACKORDER_ALLOWED', 'رزرو می‌تواند از موجودی آزاد بیشتر شود.'),
    ('BIN_LOCATIONS', 'تعریف سالن، راهرو، قفسه، طبقه و خانه در انبار.'),
    ('WAREHOUSE_ACCESS_CONTROL', 'برگهٔ کاربران مجاز و سطح دسترسی در فرم انبار.')
) AS v(code, d) WHERE feature_code = v.code;
UPDATE inv.feature_definitions SET name = 'پیشنهاد بچ زودانقضا (اول منقضی، اول خارج)' WHERE feature_code = 'FEFO_ALLOCATION';
UPDATE inv.feature_definitions SET name = 'محل‌های داخلی انبار' WHERE feature_code = 'BIN_LOCATIONS';
