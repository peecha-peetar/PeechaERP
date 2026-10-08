-- پیچا R289 — نام‌های فارسی روان برای داده‌های پیش‌فرض ارتباط با مشتری (فقط نام و متن؛ ساختار تغییری ندارد).
-- جای‌نگهدارهای انگلیسی ({name} و ...) همچنان کار می‌کنند؛ این‌جا فقط به معادل فارسی ({نام} و ...) برگردانده می‌شوند.
-- برگشت: db/rollback/209_crm_persian_labels_down.sql

UPDATE crm.sla_policies SET name = 'اولویت ' || substr(name, 5)
 WHERE name IN ('SLA بحرانی', 'SLA بالا', 'SLA عادی', 'SLA کم');

UPDATE crm.segments SET name = 'مشتریان ویژه' WHERE is_system AND code = 'VIP' AND name = 'مشتریان ویژه (VIP)';

UPDATE crm.automation_rules SET name = 'احتمال ریزش زیاد ← جلسه' WHERE name = 'ریسک ریزش زیاد ← جلسه';

UPDATE crm.automation_rules
   SET action_params = replace(replace(replace(replace(replace(replace(replace(action_params::text,
       '{name}', '{نام}'), '{company}', '{شرکت}'), '{balance}', '{مانده}'), '{overdue}', '{معوق}'),
       '{days}', '{روز}'), '{amount}', '{مبلغ}'), '{subject}', '{موضوع}')::jsonb
 WHERE action_params::text ~ '\{(name|company|balance|overdue|days|amount|subject)\}';

UPDATE crm.message_templates
   SET body = replace(replace(replace(replace(replace(replace(replace(body,
       '{name}', '{نام}'), '{company}', '{شرکت}'), '{balance}', '{مانده}'), '{overdue}', '{معوق}'),
       '{days}', '{روز}'), '{amount}', '{مبلغ}'), '{subject}', '{موضوع}'),
       subject = replace(replace(replace(replace(replace(replace(replace(subject,
       '{name}', '{نام}'), '{company}', '{شرکت}'), '{balance}', '{مانده}'), '{overdue}', '{معوق}'),
       '{days}', '{روز}'), '{amount}', '{مبلغ}'), '{subject}', '{موضوع}')
 WHERE body ~ '\{(name|company|balance|overdue|days|amount|subject)\}'
    OR subject ~ '\{(name|company|balance|overdue|days|amount|subject)\}';
