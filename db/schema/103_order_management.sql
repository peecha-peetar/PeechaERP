-- طبقِ درخواستِ صریح: زیرماژولِ «مدیریتِ سفارشات» -- یک تفصیلیِ خاص از
-- یک گروهِ تفصیلی (که خودِ شرکت به‌عنوانِ «سفارشاتِ در راه» تعیین می‌کند)
-- به‌عنوانِ یک «سفارش» انتخاب می‌شود؛ پرداخت‌هایِ آن (با هر روش/ارزی که
-- در فرمِ دریافت/پرداختِ خزانه‌داری موجود است) مستقیماً همان فرم را باز
-- می‌کند -- سندِ حسابداری خودِ همان فرم صادر می‌شود، این‌جا دوباره ساخته
-- نمی‌شود. تاریخچهٔ پرداخت‌ها با پرس‌وجویِ مستقیمِ acc.journal_entry_lines
-- (بر اساسِ همان تفصیلی) به‌دست می‌آید -- نیازی به جدولِ واسطه نیست.

-- تنظیمِ یک‌باره: کدام گروهِ تفصیلی «سفارشاتِ در راه» است.
CREATE TABLE comm.order_tracking_settings (
    company_id INT PRIMARY KEY REFERENCES core.companies(company_id),
    dimension_type_id INT NOT NULL REFERENCES acc.detail_dimension_types(dimension_type_id)
);

-- خودِ سفارش‌ها: هر ردیف دقیقاً یک تفصیلیِ همان گروه را دنبال می‌کند و
-- وضعیتِ باز/بسته‌بودنش را نگه می‌دارد.
CREATE TABLE comm.order_trackings (
    order_tracking_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    detail_account_id INT NOT NULL UNIQUE REFERENCES acc.detail_accounts(detail_account_id),
    description VARCHAR(500) NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'OPEN' CHECK (status_code IN ('OPEN', 'CLOSED')),
    opened_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    opened_at TIMESTAMP NOT NULL DEFAULT now(),
    closed_by_user_id INT NULL REFERENCES sec.users(user_id),
    closed_at TIMESTAMP NULL
);

CREATE INDEX ix_comm_order_trackings_company ON comm.order_trackings (company_id, status_code);
