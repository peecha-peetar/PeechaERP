-- Field Sales: طبقِ درخواستِ صریحِ کاربر («در تنظیماتِ موبایل بشه مرکزِ
-- هزینه و پروژه را تعیین کرد») -- سفارش‌هایِ ثبت‌شده از موبایل (پخشِ
-- گرم/VAN_SALES) وقتی به حسابی با مرکزِ هزینه/پروژهٔ الزامی پست می‌شوند
-- (journal_entries.create_journal_entry)، باید این دو مقدار را داشته
-- باشند -- ویزیتور در محل نباید مجبور به انتخابِ آن‌ها باشد، پس یک
-- پیش‌فرضِ ثابت رویِ خودِ کانال (هم‌الگو با default_warehouse_id/
-- default_price_list_idِ موجود) تعریف می‌شود.

ALTER TABLE comm.channels
    ADD COLUMN default_cost_center_detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id),
    ADD COLUMN default_project_detail_account_id INT REFERENCES acc.detail_accounts(detail_account_id);
