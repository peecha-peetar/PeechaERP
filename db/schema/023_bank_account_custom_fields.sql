-- پیچا | فیلدهایِ اختصاصیِ پیش‌فرضِ گروهِ تفصیلیِ «بانک» (نوعِ حساب/شماره‌
-- حساب/شبا/شعبه) — از همان مکانیزمِ عمومیِ acc.detail_group_fields که از
-- قبل برایِ گروه‌هایِ تفصیلی وجود دارد، فقط این‌بار برایِ شرکت‌هایِ *موجود*
-- که BANK_ACCOUNT از قبل (طبقِ 011_coding_settings.sql) برایشان ساخته
-- شده بود؛ برایِ شرکت‌هایِ تازه همین کار در ensure_specialized_dimensions
-- (services/detail_dimensions.py) انجام می‌شود.
-- پیش‌نیاز: 010_detail_group_hierarchy.sql, 011_coding_settings.sql

INSERT INTO acc.detail_group_fields (dimension_type_id, person_group_id, field_key, label, kind, is_required, sort_order)
SELECT dt.dimension_type_id, 0, seed.field_key, seed.label, 'text', FALSE, seed.sort_order
FROM acc.detail_dimension_types dt
CROSS JOIN (VALUES
    ('account_type', 'نوعِ حساب (جاری/پس‌انداز)', 0),
    ('account_number', 'شماره‌حساب', 1),
    ('iban', 'شماره‌شبا', 2),
    ('branch', 'شعبه', 3)
) AS seed(field_key, label, sort_order)
WHERE dt.code = 'BANK_ACCOUNT'
ON CONFLICT (dimension_type_id, person_group_id, field_key) DO NOTHING;
