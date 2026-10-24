-- پیچا R240: زیرساختِ دادهٔ مرحلهٔ ۳ گزارش‌گیریِ خرید -- فقط افزایشی (ستونِ nullable و جدولِ تازه).
-- هیچ ستون/جدولِ موجودی حذف یا تغییرِ نوع داده نمی‌شود و داده‌یِ قبلی دست نمی‌خورد.
--
-- بازگشت (rollback) در صورتِ نیاز:
--   ALTER TABLE comm.commercial_document_lines DROP COLUMN IF EXISTS expected_delivery_date;
--   ALTER TABLE comm.commercial_documents DROP COLUMN IF EXISTS purchase_type_id, DROP COLUMN IF EXISTS cancellation_reason_id,
--     DROP COLUMN IF EXISTS cancellation_note, DROP COLUMN IF EXISTS cancelled_at, DROP COLUMN IF EXISTS cancelled_by_user_id,
--     DROP COLUMN IF EXISTS approved_at, DROP COLUMN IF EXISTS approved_by_user_id;
--   DROP TABLE IF EXISTS comm.document_change_log, comm.cancellation_reasons, comm.purchase_types;

-- ۱) تاریخِ تحویلِ مورد انتظار در سطحِ ردیف (خالی = تاریخِ تحویلِ سرِ سند)
ALTER TABLE comm.commercial_document_lines ADD COLUMN IF NOT EXISTS expected_delivery_date DATE NULL;

-- ۲) نوعِ خرید (برنامه‌ریزی‌شده/اضطراری/...) -- اطلاعاتِ پایهٔ قابلِ‌تعریف برایِ هر شرکت
CREATE TABLE IF NOT EXISTS comm.purchase_types (
    purchase_type_id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    is_emergency BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, code)
);

-- ۳) علت‌هایِ لغوِ سند
CREATE TABLE IF NOT EXISTS comm.cancellation_reasons (
    reason_id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (company_id, code)
);

ALTER TABLE comm.commercial_documents
    ADD COLUMN IF NOT EXISTS purchase_type_id INT NULL REFERENCES comm.purchase_types(purchase_type_id),
    ADD COLUMN IF NOT EXISTS cancellation_reason_id INT NULL REFERENCES comm.cancellation_reasons(reason_id),
    ADD COLUMN IF NOT EXISTS cancellation_note TEXT NULL,
    ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS cancelled_by_user_id INT NULL REFERENCES sec.users(user_id),
    -- ۴) تصویب‌کنندهٔ مدیر (تا پیش از این ذخیره نمی‌شد)
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS approved_by_user_id INT NULL REFERENCES sec.users(user_id);

-- ۵) تاریخچهٔ وضعیت و تغییراتِ اسنادِ بازرگانی (فقط افزودنی؛ هرگز ویرایش/حذف نمی‌شود)
CREATE TABLE IF NOT EXISTS comm.document_change_log (
    log_id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES comm.commercial_documents(document_id),
    line_id BIGINT NULL,
    user_id INT NULL REFERENCES sec.users(user_id),
    changed_at TIMESTAMP NOT NULL DEFAULT now(),
    action VARCHAR(20) NOT NULL,          -- STATUS | ADD_LINE | UPDATE_LINE | DELETE_LINE | UPDATE_HEADER
    status_code VARCHAR(20) NULL,         -- وضعیتِ سند در لحظهٔ تغییر
    field_name VARCHAR(50) NULL,
    old_value TEXT NULL,
    new_value TEXT NULL
);
CREATE INDEX IF NOT EXISTS ix_document_change_log_document ON comm.document_change_log (document_id, changed_at);
