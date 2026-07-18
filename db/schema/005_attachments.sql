-- پیچا | ضمائم سند: فایل‌های پیوست‌شده به هر سند از هر ماژول
-- PostgreSQL 13+
-- پیش‌نیاز: 002_security_rbac.sql

CREATE SCHEMA doc;

-- خودِ فایل در دیتابیس ذخیره نمی‌شود؛ در فضای ذخیره‌سازی (فایل‌سرور/آبجکت‌
-- استوریج) نگه‌داری می‌شود و این جدول فقط متادیتا + مسیر/کلید فایل را دارد.
-- الگوی ارجاع دقیقاً مثل wf.CartableItems است: FormID + SourceRecordID (نرم،
-- بدون FK واقعی، چون نوع منبع بسته به نوع سند فرق می‌کند).
CREATE TABLE doc.Attachments (
    AttachmentID     BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    CompanyID        INT          NOT NULL REFERENCES core.Companies(CompanyID),
    FormID           INT          NOT NULL REFERENCES sec.Forms(FormID),
    SourceRecordID   BIGINT       NOT NULL,
    FileName         VARCHAR(260) NOT NULL,
    FileExtension    VARCHAR(20)  NOT NULL,
    FileSizeBytes    BIGINT       NOT NULL,
    StorageKey       VARCHAR(500) NOT NULL,   -- مسیر/کلید فایل در فضای ذخیره‌سازی
    ContentSha256    BYTEA        NULL,       -- برای بررسی صحت/جلوگیری از دستکاری فایل
    UploadedByUserID INT          NOT NULL REFERENCES sec.Users(UserID),
    UploadedAt       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    IsDeleted        BOOLEAN      NOT NULL DEFAULT FALSE,   -- حذف نرم؛ خودِ فایل هم باید در سرویس ذخیره‌سازی نگه داشته شود تا زمان پاک‌سازی نهایی
    DeletedByUserID  INT          NULL REFERENCES sec.Users(UserID),
    DeletedAt        TIMESTAMPTZ  NULL
);
CREATE INDEX IX_Attachments_Source ON doc.Attachments(FormID, SourceRecordID) WHERE IsDeleted = FALSE;
