-- پیچا | تکمیلِ فرمِ سندِ حسابداری طبقِ سندِ نیازمندی‌های ۲.۱:
-- شماره‌ی عطف/بایگانیِ دستی، مبدأِ سند (برای وقتی ماژول‌های دیگر مثلِ
-- خزانه/فروش/OCR خودشان سند بسازند)، کدِ مالیاتیِ هر ردیف (برای اتصالِ
-- آینده به سامانه‌ی مودیان)، و وضعیتِ «پیش‌نویس» (قبل از موقت — تا سندِ
-- ناقص/نامتعادل هم بشود موقتاً ذخیره کرد).
-- پیش‌نیاز: 003_accounting_core.sql

ALTER TABLE acc.journal_entries ADD COLUMN alternative_number VARCHAR(50) NULL;
ALTER TABLE acc.journal_entries ADD COLUMN source_system VARCHAR(20) NOT NULL DEFAULT 'MANUAL';

ALTER TABLE acc.journal_entry_lines ADD COLUMN tax_code VARCHAR(30) NULL;

INSERT INTO acc.journal_entry_statuses (status_id, code) VALUES (5, 'DRAFT');
