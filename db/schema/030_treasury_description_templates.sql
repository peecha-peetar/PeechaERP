-- طبقِ درخواستِ صریح: متنِ شرحِ خودکارِ هر روشِ ردیفِ سندِ دریافت باید
-- قابلِ‌ویرایش توسطِ کاربر باشد — یک جدولِ کلید-مقدارِ متنی، هم‌الگو با
-- treasury.account_mappings (کلیدِ آزاد، بدونِ CHECK constraint، تا
-- کلیدهایِ تازه بدونِ migration اضافه شوند).

CREATE TABLE treasury.description_templates (
    company_id     INT         NOT NULL REFERENCES core.companies(company_id),
    template_key   VARCHAR(30) NOT NULL,
    template_text  TEXT        NOT NULL,
    PRIMARY KEY (company_id, template_key)
);
