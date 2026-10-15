-- Field Sales (R134/Phase 1): اعلان‌هایِ APIِ موبایل -- مفهومی که تا این
-- migration اصلاً در ERP وجود نداشت (نه دسکتاپ، نه API). هر ردیف یک
-- اعلانِ متعلق به یک کاربرِ مشخص است (مثلاً «مشتریِ جدید نیازِ تایید
-- دارد») -- ساده و مستقل، بدونِ وابستگی به موتورِ کارتابل/گردشِ‌کار
-- (wf.*) که برایِ چیزِ دیگری (تاییدِ چندمرحله‌ایِ اسناد) طراحی شده.

CREATE TABLE sec.notifications (
    notification_id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    user_id INT NOT NULL REFERENCES sec.users(user_id),
    type_code VARCHAR(30) NOT NULL,
    title VARCHAR(200) NOT NULL,
    body TEXT,
    entity_type VARCHAR(50),
    entity_id INT,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_notifications_user_unread ON sec.notifications (user_id, company_id, is_read);
