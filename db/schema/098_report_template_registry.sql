-- رجیستریِ گزارش‌هایِ حرفه‌ایِ قابلِ‌تخصیص برایِ هر فرم -- طبقِ درخواستِ
-- صریح («برایِ هر فرم بتوان چند گزارشِ نام‌گذاری‌شده تعریف/ویرایش/اجرا
-- کرد»): هر ردیف یک نسخه‌یِ اختصاصیِ jrxml (کپی‌شده از قالبِ پایه‌یِ همان
-- فرم، آزادانه در Jaspersoft Studio قابلِ‌ویرایش) را به یک نامِ دلخواه
-- نسبت می‌دهد. خودِ فایل روی دیسک (زیرِ پوشه‌یِ دادهٔ برنامه، نه در این
-- جدول) نگه داشته می‌شود -- این جدول فقط اسم/نگاشت را نگه می‌دارد.
-- form_code عمداً بدونِ CHECK محدود نشده: لیستِ فرم‌هایِ پشتیبانی‌شده در
-- کدِ پایتون (peecha.reporting.registry.FORM_DEFINITIONS) نگه‌داری
-- می‌شود، تا افزودنِ فرمِ جدید نیازِ migration نداشته باشد.
CREATE SCHEMA IF NOT EXISTS rpt;

CREATE TABLE rpt.report_templates (
    report_template_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    form_code VARCHAR(40) NOT NULL,
    name VARCHAR(150) NOT NULL,
    file_name VARCHAR(120) NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_rpt_report_templates_name UNIQUE (company_id, form_code, name),
    CONSTRAINT uq_rpt_report_templates_file UNIQUE (company_id, file_name)
);
