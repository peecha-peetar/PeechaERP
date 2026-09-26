-- طبقِ رفعِ باگِ واقعی («در فرمِ تاییدِ سرپرست، برایِ حسابِ مشتری مرکزِ
-- هزینه/پروژه می‌خواهد -- باید در تنظیماتِ تک‌فروشی وارد بشه»): مرکزِ
-- هزینه/پروژهٔ پیش‌فرض برایِ طرفِ حسابِ دریافتنیِ مشتری (بستانکارِ
-- سندِ RECEIPTِ فروشِ حضوری).
ALTER TABLE comm.pos_settings
    ADD COLUMN default_receivable_cost_center_detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id),
    ADD COLUMN default_receivable_project_detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id);
