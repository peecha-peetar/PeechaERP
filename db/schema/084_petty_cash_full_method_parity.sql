-- پیچا | طبقِ درخواستِ صریح: همه‌یِ روش‌هایِ پرداختِ فرمِ دریافت/پرداخت
-- (به‌جز خرجِ چک، که منطقِ حسابداریِ جداگانه دارد) باید در فرمِ تنخواه
-- هم موجود باشند — نقد/بانک/چک/تخفیف/تهاتر + هر روشِ سفارشیِ فعالِ
-- همان شرکت (کدشان CUSTOM_<id>). محدودیتِ قبلیِ ستون فقط سه روش را
-- مجاز می‌کرد و طولِ ستون هم برایِ کدهایِ سفارشیِ طولانی‌تر کافی نبود.

ALTER TABLE treasury.petty_cash_fund_lines DROP CONSTRAINT petty_cash_fund_lines_method_check;
ALTER TABLE treasury.petty_cash_fund_lines ALTER COLUMN method TYPE VARCHAR(40);
