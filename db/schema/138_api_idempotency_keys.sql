-- طبقِ محدودیتِ شناخته‌شده‌یِ مستندشده در R132 (mobile/src/sync/idempotency.ts):
-- اپِ موبایل برایِ هر اقدامِ صف‌آفلاین (شروعِ ویزیت/ثبتِ سفارش/تاییدِ
-- تحویل) یک کلیدِ یکتا می‌سازد، ولی سرور تا این‌جا آن را بررسی نمی‌کرد --
-- یعنی اگر پاسخِ یک درخواستِ واقعاً موفق به‌خاطرِ قطعیِ نیمه‌کاره‌یِ شبکه
-- به کلاینت نرسد، تلاشِ دوباره‌یِ کلاینت (با همان کلید) یک فاکتور/ویزیتِ
-- تکراری می‌ساخت. این جدول همان پاسخِ اولین اجرایِ موفق را ذخیره می‌کند
-- تا درخواست‌هایِ تکراری (idempotency_key یکسان) بدونِ اجرایِ دوباره‌یِ
-- منطق، همان پاسخ را برگردانند.
CREATE TABLE sec.api_idempotency_keys (
    user_id INT NOT NULL REFERENCES sec.users(user_id),
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    idempotency_key VARCHAR(200) NOT NULL,
    endpoint VARCHAR(100) NOT NULL,
    response_status SMALLINT NOT NULL,
    response_body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, idempotency_key)
);
