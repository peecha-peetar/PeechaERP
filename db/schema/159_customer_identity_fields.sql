-- پیچا | فیلدهایِ هویتیِ تکمیلیِ مشتری (R216) -- طبقِ درخواستِ صریحِ کاربر
-- (بازبینیِ ساختارِ «تعریفِ مشتری»، بخشِ ۱): نوعِ مشتری، نوعِ شخصیت،
-- طبقه‌بندیِ ABCD، منطقه‌یِ جغرافیایی. هم‌الگو با ستون‌هایِ موجودِ
-- acc.customer_details (economic_code/national_id/...) -- نه extra_fieldsِ
-- عمومی، چون CustomerDetail از قبل جدولِ ستون‌دارِ اختصاصیِ خودش را دارد.

ALTER TABLE acc.customer_details
    ADD COLUMN customer_type_code VARCHAR(20) NULL
        CHECK (customer_type_code IN ('INDIVIDUAL', 'COMPANY', 'STORE', 'ORGANIZATION', 'WHOLESALER', 'RETAILER', 'AGENT', 'ONLINE')),
    ADD COLUMN person_type_code VARCHAR(10) NULL
        CHECK (person_type_code IN ('NATURAL', 'LEGAL')),
    ADD COLUMN customer_class VARCHAR(1) NULL
        CHECK (customer_class IN ('A', 'B', 'C', 'D')),
    ADD COLUMN geographic_region VARCHAR(100) NULL;
