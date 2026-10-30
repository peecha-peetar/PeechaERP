-- پیچا | R374: گزارش‌ساز آزاد — تعریف ذخیره‌شدهٔ گزارش (مجموعه‌داده، ستون‌ها، فیلترها، گروه‌بندی، مرتب‌سازی)، شخصی یا اشتراکی.
-- داده فقط از مجموعه‌داده‌های ثابت برنامه خوانده می‌شود؛ هیچ پرس‌وجویی از متن کاربر ساخته نمی‌شود.
CREATE TABLE IF NOT EXISTS rpt.custom_reports (
    report_id       INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id      INT           NOT NULL REFERENCES core.companies(company_id),
    owner_user_id   INT           NOT NULL REFERENCES sec.users(user_id),
    name            VARCHAR(150)  NOT NULL,
    dataset_code    VARCHAR(40)   NOT NULL,
    definition      JSONB         NOT NULL DEFAULT '{}'::jsonb,
    is_shared       BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT uq_rpt_custom_reports_name UNIQUE (company_id, owner_user_id, name)
);
