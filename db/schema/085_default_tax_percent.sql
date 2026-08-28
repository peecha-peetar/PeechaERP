-- پیچا | طبقِ درخواستِ صریح: درصدِ مالیات (بعدِ تخفیف) باید با اولویت از
-- کالا، سپس از تنظیماتِ کلیِ شرکت خوانده شود — نه همیشه صفر/دستی.

ALTER TABLE core.companies ADD COLUMN default_tax_percent NUMERIC(5, 2);
ALTER TABLE inv.items ADD COLUMN default_tax_percent NUMERIC(5, 2);
