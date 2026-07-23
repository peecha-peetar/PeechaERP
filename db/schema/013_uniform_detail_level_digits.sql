-- پیچا | یکسان‌سازیِ تعدادِ رقمِ هر سطحِ تفصیلی (سراسری برایِ همه‌ی گروه‌ها) +
-- سقفِ «تعدادِ سطح»یِ قابل‌تنظیم به‌ازایِ هر گروه (شاملِ مشتری/تامین‌کننده/پرسنل).
-- پیش‌نیاز: 003_accounting_core.sql, 009_person_groups.sql, 010_detail_group_hierarchy.sql, 012_person_group_field_config.sql
--
-- طبقِ درخواستِ صریح: «تعداد ارقام در همه گروهها مشابه هم باشه فقط بازه فرق
-- داشته باشه و تعداد سطوح تفصیلی» — تعدادِ رقمِ هر سطح از این پس یک تنظیمِ
-- سراسریِ شرکت است (نه مخصوصِ هر گروه)؛ بازه‌ی از-تا همچنان مخصوصِ هر گروه
-- می‌ماند (acc.detail_group_levels). هر گروه (کالا/بانک/... و مشتری/
-- تامین‌کننده/پرسنل) هم یک سقفِ «تعدادِ سطح» می‌گیرد تا مثلاً مشتری فقط ۲
-- سطح داشته باشد و سطحِ ۳/۴ اصلاً قابلِ‌ساخت نباشد.

CREATE TABLE acc.detail_level_digit_config (
    company_id  INT      NOT NULL REFERENCES core.companies(company_id),
    level_no    SMALLINT NOT NULL CHECK (level_no BETWEEN 1 AND 4),
    code_length SMALLINT,
    CONSTRAINT pk_detail_level_digit_config PRIMARY KEY (company_id, level_no)
);

ALTER TABLE acc.detail_group_levels DROP COLUMN code_length;

ALTER TABLE acc.detail_dimension_types
    ADD COLUMN max_level_no SMALLINT NOT NULL DEFAULT 4 CHECK (max_level_no BETWEEN 1 AND 4);

ALTER TABLE acc.person_groups
    ADD COLUMN max_level_no SMALLINT NOT NULL DEFAULT 1 CHECK (max_level_no BETWEEN 1 AND 4);
