-- طبقِ درخواستِ صریح («این تنظیمات در قسمتِ تنظیماتِ کاربر با نقشِ
-- صندوق‌دار باید تعریف بشه»): هر کاربر می‌تواند ترمینال/فهرستِ‌قیمت/
-- مشتریِ پیش‌فرضِ خودش را داشته باشد تا صفحه‌یِ فروشِ حضوری دیگر هر بار
-- این‌ها را از او نپرسد.

-- طبقِ ماهیتِ چندشرکتیِ برنامه: ترمینال/فهرستِ‌قیمت/مشتری همه به یک
-- شرکتِ مشخص تعلق دارند، پس تنظیماتِ صندوق‌داری هم باید به‌ازایِ هر
-- (کاربر، شرکت) جداگانه باشد -- نه فقط کاربر.
CREATE TABLE comm.pos_cashier_settings (
    user_id BIGINT NOT NULL REFERENCES sec.users(user_id),
    company_id BIGINT NOT NULL REFERENCES core.companies(company_id),
    default_terminal_id BIGINT REFERENCES comm.pos_terminals(terminal_id),
    default_price_list_id BIGINT REFERENCES comm.price_lists(price_list_id),
    default_customer_detail_account_id BIGINT REFERENCES acc.detail_accounts(detail_account_id),
    PRIMARY KEY (user_id, company_id)
);

-- طبقِ رفعِ شکافِ کشف‌شده در پاسخ‌هایِ ثبت‌شده («کاریر فقط confirm می‌کند
-- و نوعِ پرداختِ موردنظرش صرفاً یادداشت می‌شود؛ ثبتِ واقعیِ پرداخت/سندِ
-- حسابداری با تاییدِ سرپرست، جداگانه انجام می‌شود»): این ستون نوعِ
-- پرداختِ اعلام‌شده توسطِ کاریر (نقدی/نسیه) را نگه می‌دارد تا سرپرست در
-- زمانِ تاییدِ نهایی بداند فاکتور قرار است چگونه تسویه شود.
ALTER TABLE comm.commercial_documents
    ADD COLUMN pos_intended_payment_type VARCHAR(10);
