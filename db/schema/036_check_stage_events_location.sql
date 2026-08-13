-- طبقِ درخواستِ صریح: «سندِ مرحله‌یِ آخر حذف بشه تا چک برگرده به حالتِ
-- اول» — برایِ بازگردانیِ دقیقِ محلِ فعلیِ چک به حالتِ پیش از یک مرحله،
-- خودِ آن مرحله باید محلِ «قبل» را هم نگه دارد (نه فقط وضعیت را).

ALTER TABLE treasury.check_stage_events
    ADD COLUMN from_location_account_id        INT NULL REFERENCES acc.chart_of_accounts(account_id),
    ADD COLUMN from_location_detail_account_id  INT NULL REFERENCES acc.detail_accounts(detail_account_id);
