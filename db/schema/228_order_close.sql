-- R336: اتمام سفارش نیمه‌تمام (خرید/فروش/پیش‌فاکتور): ماندهٔ تحویل‌نشده بسته می‌شود و سفارش دیگر به فاکتور
-- تبدیل نمی‌شود. وضعیت سند تغییر نمی‌کند؛ فقط زمان، کاربر و علت اتمام ثبت می‌شود و با بازگشایی پاک می‌شود.
ALTER TABLE comm.commercial_documents ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;
ALTER TABLE comm.commercial_documents ADD COLUMN IF NOT EXISTS closed_by_user_id INT REFERENCES sec.users(user_id);
ALTER TABLE comm.commercial_documents ADD COLUMN IF NOT EXISTS close_note TEXT;
