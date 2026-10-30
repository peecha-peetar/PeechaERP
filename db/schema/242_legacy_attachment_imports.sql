-- پیچا | R354: پیوست قدیمی (doc.attachments) که به سامانهٔ اسناد منتقل شده است؛ پیوست اصلی دست نمی‌خورد
CREATE TABLE IF NOT EXISTS doc.legacy_attachment_imports (
    attachment_id        BIGINT       PRIMARY KEY REFERENCES doc.attachments(attachment_id) ON DELETE CASCADE,
    company_id           INT          NOT NULL REFERENCES core.companies(company_id),
    dms_document_id      BIGINT       NOT NULL REFERENCES doc.documents(document_id) ON DELETE CASCADE,
    imported_by_user_id  INT          NOT NULL REFERENCES sec.users(user_id),
    imported_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);
