-- پیچا | CRMِ کامل: شکایت/جلسه/فرصتِ فروش/وظیفه (R219، بخشِ ۱۱) -- یک
-- جدولِ عمومیِ فعالیت (نه چهار جدولِ موازی)، هم‌الگو با
-- customer_sales_notes/customer_call_logsِ موجود (که هم‌چنان دست‌نخورده
-- می‌مانند -- این‌ها «یادداشت»/«تماس» ساده‌اند، نه فعالیتِ ساختاریافته).

CREATE TABLE comm.customer_activities (
    activity_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    customer_detail_account_id INT NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    activity_type_code VARCHAR(15) NOT NULL
        CHECK (activity_type_code IN ('COMPLAINT', 'MEETING', 'OPPORTUNITY', 'TASK')),
    subject VARCHAR(200) NOT NULL,
    description VARCHAR(1000) NULL,
    status_code VARCHAR(15) NOT NULL DEFAULT 'OPEN'
        CHECK (status_code IN ('OPEN', 'IN_PROGRESS', 'DONE', 'RESOLVED', 'WON', 'LOST', 'CANCELLED')),
    -- برایِ TASK/MEETING: سررسید/تاریخِ جلسه. برایِ OPPORTUNITY: تاریخِ برآوردیِ نهایی‌شدن.
    due_date DATE NULL,
    estimated_value NUMERIC(18, 2) NULL,
    assigned_to_user_id INT NULL REFERENCES sec.users(user_id),
    created_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ NULL,
    resolved_by_user_id INT NULL REFERENCES sec.users(user_id)
);

CREATE INDEX ix_comm_customer_activities_customer ON comm.customer_activities (customer_detail_account_id, created_at DESC);
CREATE INDEX ix_comm_customer_activities_assigned ON comm.customer_activities (assigned_to_user_id, status_code);
