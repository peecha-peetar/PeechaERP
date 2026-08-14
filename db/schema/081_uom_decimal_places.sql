-- پیچا | تعدادِ اعشارِ مجاز برایِ هر واحدِ اندازه‌گیری — طبقِ گزارشِ صریح:
-- فیلدِ «مقدار» در ثبتِ ردیفِ سندِ انبار باید تعدادِ اعشارش را از تعریفِ
-- واحد (UOM) به ارث ببرد، نه همیشه ۶ رقمِ اعشار (که برایِ واحدهایِ
-- شمارشی مثلِ «عدد» بی‌معناست و باید عددِ صحیح باشد).
ALTER TABLE inv.uom
    ADD COLUMN decimal_places SMALLINT NOT NULL DEFAULT 2 CHECK (decimal_places BETWEEN 0 AND 6);

-- واحدهایِ شمارشیِ موجود (COUNT) به‌طورِ پیش‌فرض عددِ صحیح‌اند.
UPDATE inv.uom SET decimal_places = 0 WHERE uom_type_code = 'COUNT';
