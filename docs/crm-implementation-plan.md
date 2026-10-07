# CRM Implementation Plan — پیچا

این سند خروجیِ فاز ۱ (بررسیِ معماری، بدون تغییر کد) است و مبنای اجرای فازهای ۲ تا ۹ قرار می‌گیرد.
اصلِ حاکم: **CRM لایه‌ای روی ERP است، نه کنارِ آن** — مشتری، فروش، دریافت، مانده، انبار و پخش فقط
ارجاع/پرس‌وجو/هدایت می‌شوند؛ هیچ منطق یا دادهٔ موازی ساخته نمی‌شود.

---

## ۱. نقشهٔ معماریِ فعلی

| لایه | محل | نکته برای CRM |
|---|---|---|
| دسکتاپ PySide6 (MDI) | `src/peecha/ui` | پوسته `shell_window.py`، ثبت صفحه با `register_screen`، منو از `nav_catalog.py` |
| منطق کسب‌وکار | `src/peecha/services/*.py` | همهٔ منطق اینجاست؛ API و UI فقط صدا می‌زنند |
| مدل‌ها | `src/peecha/db/models/*.py` | SQLAlchemy، اسکیماهای `acc, comm, inv, treasury, sec, audit, wf, prd, fa, hr, ...` |
| مهاجرت | `db/schema/NNN_*.sql` | شماره‌دار، فقط رو به جلو، با `apply_pending_schema_files` |
| API موبایل | `src/peecha_api/routers` | FastAPI نازک؛ `require_permission(form, action)` روی همان RBAC |
| موبایل | `mobile/` (Expo 57) | آفلاین‌اول؛ نوشتن‌ها از `offlineQueue → syncEngine`؛ خطای 4xx صف را حذف می‌کند |

---

## ۲. چه چیزهایی از قبل وجود دارد (و استفادهٔ مجدد می‌شود)

### مشتری — منبعِ واحدِ حقیقت (هیچ مدل مشتریِ تازه ساخته نمی‌شود)
- `acc.detail_accounts` (هویت، کد، نام، شاخه) + `acc.customer_details` (کد اقتصادی، شناسه ملی، تلفن، موبایل، نوع شخص، کلاس، منطقه)
- `comm.customer_profiles` (گروه، فهرست قیمت، مهلت پرداخت، سقف اعتبار، کانال، **بازاریاب**، **مسیر پخش**، GPS، وضعیت، منبع جذب، نوع فروشگاه، اولویت)
- `comm.party_addresses` (چندآدرسی + GeoFence)، `comm.party_contacts`، `comm.customer_groups`، `comm.sales_representatives`
- `comm.customer_guarantees`، `comm.commercial_contracts`، `comm.customer_merchandising`
- سرویس: `commercial_partners` (ایجاد/تأیید/توقف/تشخیص تکراری/وضعیت)

### مالی (فقط خواندن)
- مانده: `treasury.get_counterparty_balance` و `get_counterparty_balances_bulk` (برای فهرست‌ها، بدون N+1)
- اعتبار: `commercial_credit.compute_customer_exposure` / `check_credit_exposure`، `customer_profiles.credit_limit_amount`
- سررسید و معوق: `commercial_settlements.list_unsettled_invoices` / `list_invoices_due_soon`، گزارش‌های «سنی‌بندی مطالبات» و «ماندهٔ حساب مشتریان» در موتور گزارش
- دفتر مشتری: `reports.list_ledger_entries(detail_account_id=…)`

### فروش (هدایت، نه بازنویسی)
- `commercial_documents`: پیش‌فاکتور فروش = **Quotation** (`SALES_PROFORMA`)، `SALES_ORDER`، `SALES_INVOICE`، `convert_to_invoice`، `confirm/approve/post_document`
- آمار: `summarize_customer_purchases`، `compute_customer_segment`، `compute_customer_profit`، `suggest_frequently_bought_together`
- دستیار فروش: `sales_assistant.list_customer_scores` (امتیاز ۰ تا ۱۰۰ و رده) و `get_daily_actions` (ریسک ریزش، فروش مکمل، رشد)

### دریافت/پرداخت
- `treasury.create_treasury_voucher` (سند دریافت چندروشی)، `comm.invoice_settlements`، وصول موبایل (`/collection`, `/payments`)

### فعالیت و ارتباط
- `comm.customer_activities` (شکایت/جلسه/فرصت/وظیفه — R219) + API و فرم موبایل
- `comm.customer_sales_notes`، `comm.customer_call_logs` (فروش تلفنی)، VoIP (`voip_ami`)
- ویزیت: `comm.visit_plans`، `comm.customer_visits` (Check-in/out، GPS، GeoFence، عکس، امضا)، `field_sales`، `field_sales_dashboard`
- پخش گرم/سرد: `distribution_runs`، `vehicle_loading`، `vehicle_settlement`، `delivery_confirmation`

### خدمات، وفاداری، بازاریابی
- `comm.service_tickets` (+ قطعات، گارانتی، RMA) — `commercial_aftersales`
- `comm.loyalty_accounts` / `loyalty_transactions` (امتیاز، کیف پول، سطح)
- `comm.sms_campaigns` + گیرندگان، `sms_gateway` (ارائه‌دهندهٔ پیامک قابل تنظیم)، `promotions`، `coupons`، `online_marketing`

### زیرساخت
- دسترسی: `sec.forms` خودکار از `nav_catalog` ساخته می‌شود؛ اکشن‌ها `VIEW CREATE EDIT DELETE PRINT EXPORT APPROVE`؛ `roles.user_has_permission`؛ الگوی نقش آماده (`production/roles_setup.py`)
- Audit: `audit.activity_log` با `services/audit.log_activity`
- اعلان: `sec.notifications` + `services/notifications` + API + صفحهٔ اعلان موبایل
- کارتابل/گردش تأیید: `wf.*` + `services/cartable.py`
- UI: `module_style` (کارت KPI، هدر، فوتر)، `FormDrawer`، داشبورد پایه با نمودار (`purchase_dashboards`)، موتور گزارش با اجرای پس‌زمینه و صفحه‌بندی (`purchase_reports`)، جست‌وجوی سراسری منو در `shell_window`
- زمان‌بند: تایمرهای ۶۰ ثانیه‌ای پوستهٔ دسکتاپ (الگوی `sms_campaign_timer`)

---

## ۳. مدل‌هایی که **نباید** ساخته شوند

| مفهوم | به‌جایش |
|---|---|
| Customer / Account / Contact / Address | `detail_accounts` + `customer_details` + `customer_profiles` + `party_contacts` + `party_addresses` |
| Salesperson | `sales_representatives` (تفصیلی) و `sec.users` |
| Quotation / Order / Invoice | `comm.commercial_documents` |
| Payment / Receipt | سند خزانه و `invoice_settlements` |
| Balance / Credit / Aging | محاسبه از حسابداری و خزانه |
| Visit / Route | `customer_visits` / `visit_plans` / مسیر پخش در پروفایل |
| Notification / Audit / Permission | جدول‌ها و سرویس‌های موجود |
| Loyalty account | `comm.loyalty_accounts` |

---

## ۴. مدل‌های تازه (اسکیمای جدید `crm`)

همه با `company_id`، کلید خارجی به جدول‌های موجود و ایندکس روی ستون‌های فیلتر/مرتب‌سازی.

| جدول | هدف |
|---|---|
| `crm.settings` | تنظیمات هر شرکت (آستانه‌های سلامت/ریزش، روزهای غیرفعالی و…) |
| `crm.lead_sources` | منابع سرنخ (قابل توسعه، با دادهٔ اولیهٔ وب‌سایت، اینستاگرام، واتس‌اپ، تلگرام، معرفی، تماس، نمایشگاه، تبلیغات، فروشگاه، ویزیتور، سایر) |
| `crm.pipelines`, `crm.pipeline_stages` | قیف قابل تنظیم؛ هر مرحله: احتمال، SLA (ساعت)، فیلدهای الزامی، اقدام بعدی، فعالیت خودکار، نوع (باز/برنده/بازنده) |
| `crm.leads` | سرنخ؛ پس از تبدیل به `converted_customer_detail_account_id` و `converted_opportunity_id` اشاره می‌کند |
| `crm.lead_scoring_rules` | قواعد امتیاز سرنخ (عامل، شرط، وزن) |
| `crm.opportunities`, `crm.opportunity_lines` | فرصت فروش و اقلام پیشنهادی (کالا از `inv.items`) |
| `crm.opportunity_documents` | پیوند فرصت ← پیش‌فاکتور/سفارش/فاکتور واقعی ERP (فقط ارجاع) |
| `crm.segments` | سگمنت پویا با تعریف قاعده‌ای (JSON)؛ اعضا هر بار محاسبه می‌شوند |
| `crm.customer_scores` | **کش محاسباتی** RFM، سلامت، ریسک ریزش، CLV و اقدام پیشنهادی (قابل محاسبهٔ مجدد؛ منبع حقیقت نیست) |
| `crm.campaigns`, `crm.campaign_members` | کمپین بازاریابی؛ مخاطبان از سگمنت؛ اجرای پیامکی از `sms_campaigns` موجود |
| `crm.sla_policies` | SLA بر اساس اولویت (بحرانی ۲ ساعت، بالا ۴، عادی ۲۴) |
| `crm.automation_rules`, `crm.automation_runs` | موتور قاعده (شرط ← اقدام) و لاگ اجرا برای جلوگیری از تکرار |
| `crm.messages` | لاگ ارتباطات خروجی/ورودی Communication Hub (برای تایم‌لاین) |

### جدول‌های موجودی که **توسعه** داده می‌شوند (فقط افزودن ستون nullable / بازکردن CHECK)
- `comm.customer_activities` ← **جدول واحد Activity**: افزودن `lead_id`، `opportunity_id`، `ticket_id`، `customer_visit_id`، `start_at`، `duration_minutes`، `priority_code`، `result_text`، `next_action`، `next_action_date`؛ نوع‌های `CALL, VISIT, FOLLOW_UP, EMAIL, MESSAGE, REMINDER, NOTE`؛ `customer_detail_account_id` اختیاری (برای فعالیتِ سرنخ). API و موبایل فعلی بدون تغییر کار می‌کنند.
- `comm.service_tickets` ← **جدول واحد Ticket/Complaint**: افزودن `company_id`، `category_code`، `priority_code`، `sla_due_at`، `first_response_at`، `resolution`، `rating`، `channel_code`، `ticket_no`؛ وضعیت‌های `OPEN, IN_PROGRESS, WAITING, RESOLVED, CLOSED` (وضعیت‌های فعلی پس‌ازفروش حفظ می‌شوند).
- `comm.loyalty_accounts` ← در فاز بازاریابی، فقط قواعد کسب امتیاز (تولد، خرید تکراری، معرفی) به‌صورت قاعدهٔ اتوماسیون.

---

## ۵. APIها (`src/peecha_api/routers/crm.py`، پیشوند `/crm`)

`/crm/leads` · `/crm/leads/{id}/convert` · `/crm/opportunities` · `/crm/opportunities/{id}/stage` ·
`/crm/opportunities/{id}/quotation` · `/crm/activities` · `/crm/tasks?bucket=today|tomorrow|week|overdue` ·
`/crm/pipelines` · `/crm/segments` · `/crm/campaigns` · `/crm/tickets` · `/crm/dashboard` · `/crm/search?q=` ·
`/crm/customers/{id}/360` · `/crm/customers/{id}/timeline`

- `/customers/{id}/360` فعلی دست‌نخورده می‌ماند (موبایل فعلی) و فقط فیلدهای تازه (سلامت، اقدام پیشنهادی، خلاصه) به آن **افزوده** می‌شود.
- هر endpoint با `require_permission("crm_…", ACTION)`؛ نوشتن‌های موبایل idempotent (`api_idempotency_keys`).

---

## ۶. مهاجرت‌ها

| فایل | محتوا |
|---|---|
| `204_crm_core.sql` | اسکیمای `crm`، settings، منابع، قیف/مراحل (+ قیف پیش‌فرض)، سرنخ، فرصت، اقلام، پیوند سند، توسعهٔ `customer_activities` |
| `205_crm_analytics.sql` | segments، customer_scores، قواعد امتیاز سرنخ |
| `206_crm_marketing.sql` | campaigns، members |
| `207_crm_service.sql` | توسعهٔ `service_tickets` + sla_policies |
| `208_crm_automation.sql` | automation_rules/runs، messages |

اصول: فقط `CREATE`/`ALTER … ADD COLUMN NULL`/بازکردن `CHECK` (هیچ `DROP` یا تغییر رفتار داده)، `IF NOT EXISTS` برای اجرای دوباره، و برای هر مهاجرت یک اسکریپت برگشت در `db/rollback/NNN_*_down.sql` (اجرای دستی؛ سیستم مهاجرت فعلی فقط رو به جلو است).

---

## ۷. UIها (دسکتاپ)

ماژول تازه در منو: **«مدیریت ارتباط با مشتری (CRM)»** با همان Design System (کارت KPI، هدر جمع‌وجور، Drawer، جدول، تب):

1. **داشبورد CRM** — امروز / فروش / مشتریان / مالی (کارت‌های قابل کلیک)
2. **Customer 360** — هدر: هویت + سلامت + مانده + اقدامات سریع (تماس، وظیفه، ویزیت، یادداشت، فرصت، سفارش، دریافت، تیکت)؛ تب‌ها: نمای کلی، تایم‌لاین، فروش، دریافت‌ها، فعالیت‌ها، ویزیت‌ها، تیکت‌ها، فرصت‌ها، یادداشت‌ها، اسناد؛ اقدام‌های هوشمند و «خلاصهٔ مشتری»
3. **سرنخ‌ها** — فهرست با فیلتر هوشمند و Drawer جزئیات، تبدیل به مشتری/فرصت
4. **قیف فروش (Kanban)** — ستون هر مرحله با کارت فرصت، کشیدن‌ورهاکردن، جمع ارزش وزنی
5. **مرکز کارها** — امروز (تماس، پیگیری، جلسه، ویزیت، سفارش و وصول در انتظار)، فردا، این هفته، **معوق** (قرمز)
6. **تقویم** — روز/هفته/ماه
7. **سگمنت‌ها و RFM** · 8. **کمپین‌ها** · 9. **تیکت‌ها و SLA** · 10. **قواعد اتوماسیون** · 11. **گزارش‌های CRM** (روی موتور گزارش موجود) · 12. **تنظیمات CRM**

جست‌وجوی سراسری پوسته گسترش می‌یابد تا علاوه بر منو، مشتری/سرنخ/فرصت/سفارش/فاکتور/کالا/تیکت را هم پیدا کند (سرویس قابل توسعه با ثبت «منبع جست‌وجو»).

موبایل (فاز ۷): همان `Customer360Screen` با سلامت، تایم‌لاین و اقدام سریع؛ «کارهای امروز»؛ ثبت سرنخ سریع؛ پیگیری پس از ویزیت — همه روی صف آفلاین موجود.

---

## ۸. نحوهٔ یکپارچگی

| ارتباط | روش |
|---|---|
| CRM ↔ مشتری | سرنخ با `commercial_partners.create_customer` به مشتری تبدیل می‌شود (همان اعتبارسنجی و تشخیص تکراری) |
| CRM ↔ فروش | فرصت ← `create_document("SALES_PROFORMA"/"SALES_ORDER")` + `add_line`؛ ادامهٔ مسیر (تأیید، تبدیل به فاکتور، ثبت) فقط در فرم‌های فروش موجود؛ پیوند در `opportunity_documents` |
| CRM ↔ حسابداری/خزانه | مانده، معوق، اعتبار و آخرین دریافت فقط خوانده می‌شوند؛ دکمهٔ «دریافت» فرم سند دریافت موجود را با مشتری باز می‌کند |
| CRM ↔ انبار | موجودی کالا در اقلام فرصت از `inventory_engine` خوانده می‌شود |
| CRM ↔ پخش/موبایل | ویزیت همان `customer_visits` است؛ فعالیت می‌تواند به ویزیت ارجاع دهد؛ پیگیری بعد از ویزیت = فعالیت `FOLLOW_UP` |
| CRM ↔ کاربران/نقش‌ها | فرم‌های `crm_*` در `nav_catalog` (خودکار وارد `sec.forms`) + نقش‌های آماده (`CRM_USER`, `CRM_MANAGER`, `CRM_MARKETING`, `CRM_SERVICE`) به الگوی تولید. CRM_EXPORT → اکشن `EXPORT`؛ CRM_ASSIGN → فرم `crm_assign`؛ CRM_ADMIN → فرم `crm_settings` |
| CRM ↔ اعلان | `notifications.create_notification` با `entity_type` CRM |
| CRM ↔ Audit | `audit.log_activity` برای هر تغییر حساس |
| CRM ↔ گزارش | تعریف گزارش‌های CRM روی همان `ReportDef` و صفحهٔ گزارش موجود |
| AI | `services/crm/insights.py` با رابط Provider؛ پیش‌فرض قاعده‌محور، جایگزین‌پذیر با سرویس AI بدون تغییر بقیهٔ کد |
| ارتباطات | `services/crm/communication.py` با رجیستری Provider (پیامک = `sms_gateway` موجود، داخلی = اعلان؛ ایمیل/واتس‌اپ/تلگرام = جای اتصال) |

---

## ۹. ریسک‌ها و راه‌حل

| ریسک | راه‌حل |
|---|---|
| کندی Customer 360/داشبورد روی دادهٔ زیاد | پرس‌وجوی تجمیعی تکی به‌جای حلقه، `get_counterparty_balances_bulk`، کش `customer_scores` با محاسبهٔ دوره‌ای، تب‌های تنبل (فقط با بازشدن تب)، صفحه‌بندی تایم‌لاین |
| ناسازگاری با API و موبایل فعلی فعالیت‌ها | فقط افزودن ستون nullable؛ کدهای نوع قدیمی معتبر می‌مانند؛ تست رگرسیون موبایل |
| `service_tickets` فاقد `company_id` | ستون nullable + پرکردن از شرکت تفصیلی مشتری در همان مهاجرت |
| نبود زمان‌بند سروری برای اتوماسیون | اجرای idempotent (لاگ `automation_runs` با کلید یکتا) با تایمر دسکتاپ + endpoint `/crm/automation/run` برای cron |
| دسترسی‌های غیرمنویی (Assign/Admin) | فرم‌های بدون صفحه در کاتالوگ فرم (همان روش فرم‌های بهای تولید) |
| رد شدن عملیات موبایل با 4xx | در ثبت فعالیت/پیگیری، نبود تنظیمات فقط هشدار می‌دهد و عملیات را رد نمی‌کند |
| تکرار منطق فروش | CRM هیچ قیمت، مالیات یا موجودی را حساب نمی‌کند؛ فقط سند پیش‌نویس فروش را با سرویس موجود می‌سازد |
| حجم کار | تحویل فازبه‌فاز با نسخهٔ جدا، تست و رگرسیون کامل در هر فاز |

---

## ۱۰. ترتیب اجرا

| فاز | نسخه | محتوا | تست |
|---|---|---|---|
| ۱ | — | همین سند | — |
| ۲ | R281 | هستهٔ CRM: مهاجرت ۲۰۴، سرویس‌های سرنخ/فرصت/قیف/فعالیت/کار، Customer 360 دسکتاپ (هدر، تب‌ها، تایم‌لاین)، مرکز کارها، Kanban، منو و دسترسی، Audit | سرنخ← مشتری، سرنخ← فرصت، مشتری← پیگیری |
| ۳ | R282 | فرصت ← پیش‌فاکتور/سفارش؛ ردیابی سند تا فاکتور و دریافت؛ دکمه‌های سفارش و دریافت در ۳۶۰ | فرصت← فروش، مشتری← سفارش و دریافت |
| ۴ | R283 | سگمنت پویا، RFM، سلامت، ریسک ریزش، CLV، اقدام پیشنهادی، خلاصهٔ مشتری | مشتری← سگمنت، RFM، ریسک ریزش |
| ۵ | R284 | کمپین، مخاطبان از سگمنت، تحلیل کمپین، منابع و امتیاز سرنخ، وفاداری | کمپین ← سرنخ ← فروش |
| ۶ | R285 | تیکت و شکایت، SLA، رضایت | مشتری← تیکت، نقض SLA |
| ۷ | R286 | موبایل: ۳۶۰، کارهای امروز، ثبت سرنخ، پیگیری پس از ویزیت | مشتری← ویزیت، API و typecheck موبایل |
| ۸ | R287 | موتور اتوماسیون، Communication Hub، اعلان‌های CRM | قواعد غیرفعالی، مذاکره، فاکتور معوق |
| ۹ | R288 | داشبورد کامل، پیش‌بینی فروش، ۱۶ گزارش، عملکرد فروشنده، جست‌وجوی سراسری، تقویم | ماتریس یکپارچگی کامل + رگرسیون |

در پایان هر فاز: تست یکپارچگی `tests/integration/test_r28N_crm_*.py`، تست API با `TestClient`، تست UI آفلاین (offscreen)، `npm run typecheck && npm test` در فاز موبایل، و اجرای کامل `run_all.sh`.

## وضعیت نهایی پیاده‌سازی (R281 تا R288)

| فاز | نسخه | تحویل‌شده | تست |
|---|---|---|---|
| ۲ هسته | R281 | سرنخ، قیف، فرصت، فعالیت، مرکز کارها، پروندهٔ ۳۶۰، تایم‌لاین، نقش‌های آماده | `test_r281_crm_core` |
| ۳ فروش | R282 | فرصت ← پیش‌فاکتور/سفارش با سرویس اسناد موجود، زنجیرهٔ فروش، برنده‌شدن خودکار | `test_r282_crm_sales_integration` |
| ۴ تحلیل | R283 | RFM، سلامت، ریسک ریزش، CLV، اقدام پیشنهادی (Provider قابل جایگزینی)، سگمنت پویا | `test_r283_crm_analytics` |
| ۵ بازاریابی | R284 | کمپین (صف پیامک موجود)، نسبت‌دهی و ROI، باشگاه مشتریان روی حساب امتیاز موجود، امتیاز سرنخ قابل تنظیم | `test_r284_crm_marketing` |
| ۶ خدمات | R285 | تیکت/شکایت روی service_tickets، SLA، ارجاع، رضایت | `test_r285_crm_tickets` |
| ۷ موبایل | R286 | کارهای من، ثبت سرنخ، شکایت، بینش ۳۶۰، پیگیری پس از ویزیت (صف آفلاین) | `test_r286_crm_mobile_api`، `mobile/__tests__/crmSync` |
| ۸ اتوماسیون | R287 | موتور قاعده، مرکز ارتباطات با Provider، الگوی پیام، دفتر پیام، اجرای خودکار | `test_r287_crm_automation` |
| ۹ مدیریت | R288 | داشبورد، پیش‌بینی، عملکرد فروشنده، ۱۶ گزارش روی موتور گزارش موجود، جستجوی سراسری، تقویم | `test_r288_crm_dashboard_matrix` (ماتریس یکپارچگی) |

migrationها: `204` تا `208` (فقط افزودنی)، برگشت دستی در `db/rollback/`. هیچ منطق فروش، حسابداری، انبار یا تسویه بازنویسی نشد.
