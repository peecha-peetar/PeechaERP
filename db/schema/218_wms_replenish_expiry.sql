-- پیچا R307 — انبار پیشرفته، فاز ۶: تامین مجدد هوشمند و پایش انقضا (پیش‌فرض خاموش). برگشت: db/rollback/218_wms_replenish_expiry_down.sql

INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('WMS_SMART_REPLENISH', 'تامین مجدد با در نظر گرفتن رزرو و برداشت باز', 'WMS', NULL,
     'نیاز تامین مجدد محل برداشت با موجودی آزاد آن (بعد از کسر سفارش‌های رزروشده و برداشت‌های باز) سنجیده می‌شود تا محل پیش از خالی‌شدن پر شود؛ مقدار تامین از ظرفیت محل بیشتر نمی‌شود و فقط از موجودی آزاد محل‌های دیگر برداشته می‌شود.'),
    ('WMS_EXPIRY_ALERTS', 'هشدار انقضا و انتقال کالای منقضی', 'WMS', NULL,
     'بچ‌هایی که تا چند روز دیگر (قابل تنظیم) منقضی می‌شوند و بچ‌های منقضی‌شده در کارتابل انباردار و مدیر می‌آیند. برای کالای منقضی یک سند پیش‌نویس انتقال به انبار ضایعات یا قرنطینه ساخته می‌شود که پس از بررسی، خود کاربر ثبتش می‌کند.')
ON CONFLICT (feature_code) DO NOTHING;

CREATE TABLE IF NOT EXISTS inv.wms_settings (
    company_id          INT       NOT NULL PRIMARY KEY REFERENCES core.companies(company_id),
    expiry_alert_days   SMALLINT  NOT NULL DEFAULT 30 CHECK (expiry_alert_days BETWEEN 1 AND 3650),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
