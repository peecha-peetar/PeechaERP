-- طبقِ موردِ ۵ («روشِ اقساط منوط به فاکتور نباشد -- مبلغِ آزاد هم قابلِ
-- تقسیط باشد») و موردِ ۶ («درصدِ بهرهٔ اقساط و هزینه‌هایِ متفرقه، مبلغِ
-- نهاییِ محاسبه‌شده، و فاصله‌یِ سررسیدِ آزاد»): comm.installment_plans
-- دیگر لزوماً به یک سندِ تجاری وصل نیست -- document_id اختیاری می‌شود و
-- company_id/counterparty_detail_account_id/direction به‌عنوانِ جایگزینِ
-- همان اطلاعات (فقط برایِ طرحِ بدونِ فاکتور) اضافه می‌شوند. principal_amount/
-- interest_rate_percent/misc_fee_amount/due_interval_days پارامترهایِ
-- محاسبه‌یِ مبلغِ نهایی و فاصله‌یِ سررسیدِ قابلِ‌تنظیم‌اند. سهمِ هر قسط
-- از بهره/هزینه هم در installment_lines.interest_fee_amount نگه‌داری
-- می‌شود تا در تسویه/گزارش‌گیری از اصلِ مبلغ قابلِ‌تفکیک باشد.

ALTER TABLE comm.installment_plans
    ALTER COLUMN document_id DROP NOT NULL,
    ADD COLUMN company_id INT NULL REFERENCES core.companies(company_id),
    ADD COLUMN counterparty_detail_account_id INT NULL REFERENCES acc.detail_accounts(detail_account_id),
    ADD COLUMN direction VARCHAR(10) NULL CHECK (direction IN ('RECEIPT', 'PAYMENT')),
    ADD COLUMN principal_amount NUMERIC(18,2) NULL,
    ADD COLUMN interest_rate_percent NUMERIC(6,3) NOT NULL DEFAULT 0 CHECK (interest_rate_percent >= 0),
    ADD COLUMN misc_fee_amount NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (misc_fee_amount >= 0),
    ADD COLUMN due_interval_days SMALLINT NOT NULL DEFAULT 30 CHECK (due_interval_days > 0);

ALTER TABLE comm.installment_plans
    ADD CONSTRAINT ck_installment_plans_owner CHECK (
        document_id IS NOT NULL
        OR (company_id IS NOT NULL AND counterparty_detail_account_id IS NOT NULL AND direction IS NOT NULL)
    );

ALTER TABLE comm.installment_lines
    ADD COLUMN interest_fee_amount NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (interest_fee_amount >= 0);
