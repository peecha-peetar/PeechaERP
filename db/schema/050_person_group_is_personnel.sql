-- طبقِ درخواستِ صریح: «کدام گروه(هایِ) تفصیلی = پرسنل» باید تنظیم‌پذیر
-- باشد، نه هاردکدشده در کد (PERSONNEL_GROUP_CODE). این پرچم مستقل از کدِ
-- گروه است — اگر بعداً گروهِ دیگری هم برایِ پرسنل استفاده شود، همین‌جا
-- علامت می‌خورد.
ALTER TABLE acc.person_groups ADD COLUMN is_personnel BOOLEAN NOT NULL DEFAULT FALSE;

-- سازگاریِ کاملِ عقب‌رو: گروهِ سیستمیِ فعلیِ PERSONNEL (که تا امروز به‌صورتِ
-- هاردکد در کد استفاده می‌شد) از قبل «پرسنل» علامت می‌خورد تا هیچ رفتاری
-- برایِ نصب‌هایِ موجود تغییر نکند.
UPDATE acc.person_groups SET is_personnel = TRUE WHERE code = 'PERSONNEL';
