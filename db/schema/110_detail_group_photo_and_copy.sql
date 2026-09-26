-- طبقِ درخواستِ صریح («برایِ گروه‌هایی که تیک می‌زنیم عکس آپلود کرد»):
-- هر گروهِ تفصیلی (چه نوع‌بُعدِ ساده/تخصصی، چه زیرگروهِ اشخاص) می‌تواند
-- امکانِ آپلودِ عکس برایِ حساب‌هایِ تفصیلی‌اش را روشن/خاموش کند.

ALTER TABLE acc.detail_dimension_types
    ADD COLUMN photo_enabled BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE acc.person_groups
    ADD COLUMN photo_enabled BOOLEAN NOT NULL DEFAULT FALSE;
