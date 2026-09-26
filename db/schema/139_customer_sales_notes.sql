-- طبقِ درخواستِ صریحِ کاربر (صفحه‌یِ فروشِ تلفنی): برایِ هر مشتری در
-- فهرستِ مشتریانِ ویزیتور، امکانِ ثبتِ یادداشت لازم است. برخلافِ
-- acc.customer_details.notes (که یک فیلدِ تکی و قابلِ‌بازنویسی است)،
-- این یک لاگِ تاریخ‌دار است -- چون چند ویزیتور/چند تماس ممکن است
-- یادداشتِ جداگانه ثبت کنند و از دست‌رفتنِ یادداشتِ قبلی با بازنویسی
-- پذیرفتنی نیست.
CREATE TABLE comm.customer_sales_notes (
    note_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    customer_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    created_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    note_text VARCHAR(1000) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_customer_sales_notes_customer ON comm.customer_sales_notes (customer_detail_account_id, created_at DESC);
