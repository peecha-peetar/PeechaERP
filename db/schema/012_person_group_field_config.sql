-- پیچا | امکانِ پیکربندیِ تعدادِ رقم/بازه/فیلدِ اختصاصی برایِ گروه‌هایِ
-- تفصیلیِ اشخاص (مشتری/تامین‌کننده/پرسنل) هم — دقیقاً مثلِ بقیه‌ی
-- گروه‌هایِ تفصیلی (کالا/بانک/... و گروه‌هایِ سادهِ دلخواه).
-- پیش‌نیاز: 003_accounting_core.sql, 009_person_groups.sql, 010_detail_group_hierarchy.sql
--
-- طبقِ درخواستِ صریح: «همه گروه‌های تفصیلی را بتوان پیکربندی کرد حتی
-- مشتری و تامین‌کننده و پرسنل و برای هر کدام بتوان فیلدهای اختصاصیِ
-- خودش را ایجاد کرد.» مشکل: مشتری/تامین‌کننده/پرسنل هر سه زیرِ همان
-- یک نوع‌بُعدِ سیستمیِ PERSON‌اند (acc.person_groups جداشان می‌کند، نه
-- acc.detail_dimension_types) — پس acc.detail_group_levels/fields
-- (که فقط با dimension_type_id کلید می‌خورند) نمی‌توانند بینِ مشتری و
-- تامین‌کننده فرق بگذارند. ستونِ person_group_id (پیش‌فرض ۰ = «بدونِ
-- محدودیت به گروهِ خاص»، یعنی رفتارِ قبلی برایِ بقیه‌ی گروه‌ها دست‌نخورده
-- می‌ماند) این تفکیک را اضافه می‌کند.

ALTER TABLE acc.detail_group_levels
    ADD COLUMN person_group_id SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE acc.detail_group_levels DROP CONSTRAINT pk_detail_group_levels;
ALTER TABLE acc.detail_group_levels
    ADD CONSTRAINT pk_detail_group_levels PRIMARY KEY (dimension_type_id, person_group_id, level_no);

ALTER TABLE acc.detail_group_fields
    ADD COLUMN person_group_id SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE acc.detail_group_fields DROP CONSTRAINT uq_detail_group_fields;
ALTER TABLE acc.detail_group_fields
    ADD CONSTRAINT uq_detail_group_fields UNIQUE (dimension_type_id, person_group_id, field_key);
