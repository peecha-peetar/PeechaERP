-- طبقِ درخواستِ صریح: وقتی فایلِ قیمتِ تامین‌کننده هم ستونِ «کدِ کالا» و
-- هم ستونِ جداگانه‌یِ «نامِ کالا» دارد، کاربر باید بتواند هردو را
-- جداگانه انتخاب کند (نه فقط یک ستونِ ترکیبیِ «کد/نام») تا تشخیصِ کالا
-- از رویِ هردو مقدار هم‌زمان انجام شود. بنابراین code_column_index
-- دیگر همیشه اجباری نیست (ممکن است فقط ستونِ نام انتخاب شده باشد) و
-- یک ستونِ جدید برایِ اندیسِ ستونِ نام اضافه می‌شود.

ALTER TABLE comm.supplier_price_import_templates
    ALTER COLUMN code_column_index DROP NOT NULL;

ALTER TABLE comm.supplier_price_import_templates
    ADD COLUMN name_column_index SMALLINT NULL;
