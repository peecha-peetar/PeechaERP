-- پیچا | چک/سفته/ضمانت‌نامه/ضامن/وثیقه به‌عنوانِ اطلاعاتِ اعتباریِ خودِ
-- مشتری (R219، بخشِ ۵) -- طبقِ بازبینیِ ساختارِ «تعریفِ مشتری». این‌ها
-- ضمانتِ نگه‌داری‌شده‌یِ مشتری‌اند، نه چکِ دریافتیِ یک تراکنشِ خاص (آن
-- قبلاً در treasury/دریافت‌ها هست) -- جدولِ جداگانه، بدونِ اثر روی
-- خزانه‌داری تا وقتی کسی صراحتاً آن را وصول/ضبط نکند.

CREATE TABLE comm.customer_guarantees (
    guarantee_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    customer_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    guarantee_type_code VARCHAR(20) NOT NULL
        CHECK (guarantee_type_code IN ('CHECK', 'PROMISSORY_NOTE', 'BANK_GUARANTEE', 'GUARANTOR', 'COLLATERAL')),
    status_code VARCHAR(15) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status_code IN ('ACTIVE', 'RELEASED', 'CALLED', 'EXPIRED')),
    amount NUMERIC(18, 2) NOT NULL CHECK (amount >= 0),
    valid_until_date DATE NULL,
    -- فقط برایِ guarantee_type_code = CHECK.
    bank_id INT NULL REFERENCES treasury.banks(bank_id),
    check_no VARCHAR(30) NULL,
    check_due_date DATE NULL,
    -- توضیحِ آزاد: نامِ ضامن/شرحِ وثیقه/شماره‌یِ سفته/شماره‌یِ ضمانت‌نامه.
    description VARCHAR(500) NULL,
    created_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at TIMESTAMPTZ NULL,
    released_by_user_id INT NULL REFERENCES sec.users(user_id)
);

CREATE INDEX ix_comm_customer_guarantees_customer ON comm.customer_guarantees (customer_detail_account_id, status_code);
