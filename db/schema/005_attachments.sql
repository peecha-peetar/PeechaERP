-- پیچا | ضمائم سند: فایل‌های پیوست‌شده به هر سند از هر ماژول
-- PostgreSQL 13+ — شناسه‌ها snake_case هستند (بدون کوتیشن)
-- پیش‌نیاز: 002_security_rbac.sql

CREATE SCHEMA doc;

-- خودِ فایل در دیتابیس ذخیره نمی‌شود؛ در فضای ذخیره‌سازی (فایل‌سرور/آبجکت‌
-- استوریج) نگه‌داری می‌شود و این جدول فقط متادیتا + مسیر/کلید فایل را دارد.
-- الگوی ارجاع دقیقاً مثل wf.cartable_items است: form_id + source_record_id (نرم،
-- بدون FK واقعی، چون نوع منبع بسته به نوع سند فرق می‌کند).
CREATE TABLE doc.attachments (
    attachment_id       BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id           INT         NOT NULL REFERENCES core.companies(company_id),
    form_id               INT        NOT NULL REFERENCES sec.forms(form_id),
    source_record_id      BIGINT     NOT NULL,
    file_name             VARCHAR(260) NOT NULL,
    file_extension         VARCHAR(20) NOT NULL,
    file_size_bytes        BIGINT     NOT NULL,
    storage_key            VARCHAR(500) NOT NULL,   -- مسیر/کلید فایل در فضای ذخیره‌سازی
    content_sha256          BYTEA      NULL,       -- برای بررسی صحت/جلوگیری از دستکاری فایل
    uploaded_by_user_id     INT        NOT NULL REFERENCES sec.users(user_id),
    uploaded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_deleted               BOOLEAN   NOT NULL DEFAULT FALSE,   -- حذف نرم؛ خودِ فایل هم باید در سرویس ذخیره‌سازی نگه داشته شود تا زمان پاک‌سازی نهایی
    deleted_by_user_id       INT       NULL REFERENCES sec.users(user_id),
    deleted_at                TIMESTAMPTZ NULL
);
CREATE INDEX ix_attachments_source ON doc.attachments(form_id, source_record_id) WHERE is_deleted = FALSE;
