-- برگشت R289: نام‌های پیش‌فرض قبلی (جای‌نگهدارهای فارسی در هر دو حالت کار می‌کنند و برگردانده نمی‌شوند).
UPDATE crm.sla_policies SET name = 'SLA ' || substr(name, 8)
 WHERE name IN ('اولویت بحرانی', 'اولویت بالا', 'اولویت عادی', 'اولویت کم');
UPDATE crm.segments SET name = 'مشتریان ویژه (VIP)' WHERE is_system AND code = 'VIP' AND name = 'مشتریان ویژه';
UPDATE crm.automation_rules SET name = 'ریسک ریزش زیاد ← جلسه' WHERE name = 'احتمال ریزش زیاد ← جلسه';
