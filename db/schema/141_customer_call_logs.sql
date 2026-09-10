-- طبقِ درخواستِ صریحِ کاربر («مکالماتِ هر مشتری در پروفایلش ذخیره
-- بشه»): این فاز فقط تماس‌هایِ خودمان (Originateِ AMIِ R137) را ثبت
-- می‌کند -- تماسِ ورودی/CDRِ سانترال (که نیازِ اتصالِ MySQLِ جداگانه
-- به دیتابیسِ CDRِ آستریسک دارد) عمداً فازِ بعدی است تا بدونِ
-- اعتبارنامه‌یِ واقعی، چیزی حدس‌زده و تست‌نشده پیاده نشود.
CREATE TABLE comm.customer_call_logs (
    call_log_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    customer_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    agent_user_id INT NOT NULL REFERENCES sec.users(user_id),
    phone_number VARCHAR(30) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    was_successful BOOLEAN NOT NULL,
    note VARCHAR(500)
);

CREATE INDEX ix_customer_call_logs_customer ON comm.customer_call_logs (customer_detail_account_id, started_at DESC);
