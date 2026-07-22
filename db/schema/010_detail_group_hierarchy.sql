-- پیچا | سلسله‌مراتبِ حسابِ تفصیلی (تا ۴ سطح) + پیکربندیِ طولِ کدِ هر سطح
-- + فیلدهای اختصاصیِ قابل‌تعریفِ هر گروهِ تفصیلی.
-- پیش‌نیاز: 003_accounting_core.sql (acc.detail_accounts، acc.detail_dimension_types)
--
-- طبقِ درخواستِ صریحِ کاربر: «تفصیلی» یک مفهومِ چتری‌ست که چند گروه دارد
-- (مشتری/تامین‌کننده/پرسنل که از قبل با acc.person_groups پیاده شده‌اند،
-- به‌علاوه‌ی گروه‌هایی که خودِ کاربر تعریف می‌کند مثلِ بانک/صندوق‌وتنخواه/
-- دارایی‌ثابت/کالا/مرکز هزینه/پروژه/تفصیلیِ معمولی — که همه از قبل با
-- acc.detail_dimension_types پیاده شده‌اند). این افزودنی صرفاً افزایشی
-- است (بدونِ rename/drop جدول‌های موجود) تا جریانِ کاملاً تست‌شده‌ی
-- مشتری/تامین‌کننده/پرسنل و مرکز هزینه/پروژه در صدور سند دست‌نخورده بماند:
--   ۱) به acc.detail_accounts سلسله‌مراتب (والد + سطح) و فیلدهای اختصاصیِ
--      JSONB اضافه می‌شود — برای هر گروه (چه مشتری/تامین‌کننده/پرسنل، چه
--      گروه‌های تعریف‌شده‌ی کاربر).
--   ۲) acc.detail_group_levels: طولِ کدِ هر سطح (۱ تا ۴) به تفکیکِ
--      dimension_type_id — اختیاری؛ گروهی که ردیفی این‌جا نداشته باشد
--      همچنان تخت/بدونِ محدودیتِ طول می‌ماند (سازگار با رفتارِ فعلی).
--   ۳) acc.detail_group_fields: تعریفِ فیلدهای اختصاصیِ هر گروهِ
--      تعریف‌شده‌ی کاربر (dimension_type_id) — مثلاً برایِ «بانک»: شماره
--      حساب/شبا؛ برایِ «کالا»: واحدِ سنجش. مقادیرشان در
--      detail_accounts.extra_fields ذخیره می‌شود.

ALTER TABLE acc.detail_accounts
    ADD COLUMN parent_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    ADD COLUMN level_no SMALLINT NOT NULL DEFAULT 1 CHECK (level_no BETWEEN 1 AND 4),
    ADD COLUMN extra_fields JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE acc.detail_group_levels (
    dimension_type_id SMALLINT NOT NULL REFERENCES acc.detail_dimension_types(dimension_type_id),
    level_no          SMALLINT NOT NULL CHECK (level_no BETWEEN 1 AND 4),
    code_length       SMALLINT NOT NULL CHECK (code_length BETWEEN 1 AND 10),
    CONSTRAINT pk_detail_group_levels PRIMARY KEY (dimension_type_id, level_no)
);

CREATE TABLE acc.detail_group_fields (
    detail_group_field_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dimension_type_id     SMALLINT NOT NULL REFERENCES acc.detail_dimension_types(dimension_type_id),
    field_key             VARCHAR(50) NOT NULL,
    label                 VARCHAR(100) NOT NULL,
    kind                  VARCHAR(20) NOT NULL,
    is_required           BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order            SMALLINT NOT NULL DEFAULT 0,
    CONSTRAINT uq_detail_group_fields UNIQUE (dimension_type_id, field_key),
    CONSTRAINT chk_detail_group_fields_kind CHECK (kind IN ('text', 'decimal', 'date', 'boolean'))
);
