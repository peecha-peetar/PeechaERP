-- طبقِ درخواستِ صریح («در تنظیمات آپشنی باشد که تعداد مثلاً ۲ روز مانده به
-- موعدِ تسویه برنامه آلارم بدهد»): تنظیماتِ سطحِ شرکت برایِ هشدارِ نزدیک‌شدنِ
-- موعدِ تسویه -- alarm_days_before صفر/منفی یعنی «هرگز هشدار نده»، حتی
-- اگر is_enabled هم روشن باشد (سازگاریِ ایمن با پیش‌فرض).
CREATE TABLE comm.settlement_alarm_settings (
    company_id BIGINT PRIMARY KEY REFERENCES core.companies(company_id),
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    alarm_days_before SMALLINT NOT NULL DEFAULT 2
);
