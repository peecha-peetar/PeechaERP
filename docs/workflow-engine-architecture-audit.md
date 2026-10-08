# Workflow Engine Architecture Audit — پیچا

> فاز ۰ (فقط بررسی؛ هیچ کدی تغییر نکرده). مبنا: شاخهٔ `claude/item-form-p1-p15-restore` در نسخهٔ R290.
> هدف: یک «لایهٔ هماهنگ‌سازی» (Orchestration Layer) روی منطق فعلی پیچا — نه جایگزین آن.

---

## ۱. معماری فعلی (Current Architecture)

| لایه | وضعیت فعلی |
|---|---|
| دسکتاپ | PySide6، صفحه‌ها در `src/peecha/ui/screens/*.py`، پوستهٔ MDI در `ui/shell_window.py`، منو/فرم‌ها از یک منبع (`nav_catalog.py`، ۴۵۰ آیتم برگ / ۴۵۷ فرم دسترسی). |
| منطق کسب‌وکار | سرویس‌های تابعی در `src/peecha/services/` (≈۱۵۰ هزار خط پایتون در کل). هر سرویس معمولاً **session خودش** را با `new_session()` باز و commit می‌کند. |
| داده | PostgreSQL با اسکیماهای جدا (`core`, `sec`, `acc`, `treasury`, `inv`, `comm`, `hr`, `payroll`, `fa`, `prd`, `crm`, `wf`, `audit`)، SQLAlchemy 2، ۲۰۶ فایل migration شماره‌دار (`db/schema/NNN_*.sql`) با `apply_pending_schema_files()` و rollback در `db/rollback/`. |
| API | FastAPI در `src/peecha_api/` (لایهٔ نازک روی همان سرویس‌ها) با JWT، `require_permission`، `run_idempotent` و rate limit. |
| موبایل | React Native/Expo، آفلاین‌اول (`sync/offlineQueue.ts` → `syncEngine.ts`)؛ پاسخ 4xx اقدام صف را دور می‌اندازد. |
| زمان‌بندی | **هیچ سرویس پس‌زمینهٔ سروری وجود ندارد.** کارهای دوره‌ای با `QTimer` در پوستهٔ دسکتاپ اجرا می‌شوند (فروش اینترنتی، تقویم محتوا، کمپین پیامک، اتوماسیون CRM هر ۱۰ دقیقه — `shell_window.py:955-980`) و فقط وقتی برنامه باز است. |
| تست | ۱۱۰ اسکریپت یکپارچگی در `tests/integration` (رگرسیون کامل با `run_all.sh`). |

**جمع‌بندی:** یک مونولیت لایه‌ای و تمیز است. سرویس‌ها نقطهٔ درست اتصال هستند و همین ساختار برای یک Workflow Engine درون‌فرایندی کافی است. به صف پیام خارجی (RabbitMQ/Kafka/NATS) نیازی نیست.

---

## ۲. سیستم رویداد/سیگنال فعلی (Existing Event/Signal System)

- **Event Bus دامنه‌ای وجود ندارد.** هیچ publish/subscribe یا listener ORM در سرویس‌ها نیست. `Signal`های Qt فقط برای UI هستند.
- آنچه شبیه رویداد است:
  - `comm.document_change_log` (`DocumentChangeLog`): تغییر وضعیت و ردیف اسناد بازرگانی را ثبت می‌کند.
  - `treasury.check_stage_events`: مراحل چک.
  - `audit.activity_log`: رد حسابرسی تغییرناپذیر.
  - `crm.automation_log`: لاگ اجرای قاعده‌های CRM.
- **موتور قاعدهٔ CRM (R287)** در `services/crm/automation.py` مبتنی بر **پیمایش دوره‌ای** است. شش trigger دارد (مشتری بی‌خرید، فاکتور معوق، سرنخ بی‌تماس، فرصت راکد، نقض تعهد زمانی، عضو بخش مشتری) و سه action (فعالیت، اعلان، پیام). جلوی تکرار را با cooldown روی `automation_log` می‌گیرد.
  - این همان الگوی «Scheduled Scan Trigger» است که باید عمومی شود.

**نتیجه:** Event Bus باید ساخته شود؛ درون‌فرایندی و ماندگار (Transactional Outbox در PostgreSQL).

---

## ۳. سرویس‌های کسب‌وکار موجود (Existing Business Services)

نقاط انتقال وضعیت که Workflow باید **فقط صدا بزند** (بازنویسی نمی‌شوند):

| ماژول | سرویس و تابع‌های کلیدی | ماشین وضعیت فعلی |
|---|---|---|
| فروش/خرید (اسناد بازرگانی) | `commercial_documents.confirm_document`, `approve_document`, `approve_warehouse`, `approve_weighing`, `convert_to_invoice`, `post_document` | `DRAFT → CONFIRMED → APPROVED → … POSTED/CANCELLED`؛ تصویب مدیر با پرچم‌های `SALES_ORDER_MANAGER_APPROVAL`, `PURCHASE_ORDER_SKIP_APPROVAL`, … (`requires_manager_approval`) |
| اعتبار مشتری | `commercial_credit.check_credit_exposure`, `create_credit_hold`, `release_credit_hold` | قفل اعتباری روی سند |
| قیمت/تخفیف | `commercial_pricing` (`below_margin_requires_approval`, `MarginCheckResult.requires_approval`) | پرچم نیاز به تایید زیر حاشیهٔ سود |
| درخواست خرید | `purchase_requests.submit_request`, `approve_request`, `reject_request` | `DRAFT → SUBMITTED → APPROVED/REJECTED/CANCELLED` |
| RFQ / بودجه | `rfqs`, `purchase_budgets` | — |
| حسابداری/خزانه | `journal_entries.approve_journal_entry` (اسناد دریافت/پرداخت خزانه هم سند حسابداری‌اند) | موقت ← دائم |
| انبار | `inventory_documents.confirm_stock_document`, شمارش، انتقال، پرچم‌های `requires_receipt_approval`/`requires_issue_approval` انبار، `reorder_point_qty` | `DRAFT → CONFIRMED → POSTED` |
| تولید | `production/orders.py` (انتقال وضعیت، رزرو مواد)، `planning.approve_plan` | `DRAFT/PLANNED → RELEASED → IN_PROGRESS → COMPLETED → CLOSED` |
| دارایی ثابت | `fixed_assets/approval.py` (۸ عملیات حساس با «دستور معوق» و اجرا پس از تایید) | — |
| حقوق | `payroll_loans.approve_loan/reject_loan`, `payroll_engine.approve_run` | `PENDING → APPROVED`، `DRAFT → CALCULATED → APPROVED` |
| منابع انسانی | `hr.py`, `hr_attendance.py`, `payroll_overtime.py` | **درخواست مرخصی وجود ندارد**؛ اضافه‌کار وضعیت تایید ندارد |
| مشتری/تامین‌کننده | `commercial_partners.approve_customer/reject_customer`, `approve_supplier` | `PENDING_APPROVAL` |
| پخش/خودرو/خدمات | `vehicle_settlement.submit/approve_warehouse/approve_accounting`, `commercial_aftersales.approve_rma` | — |
| CRM | `crm/leads`, `opportunities`, `activities`, `tickets` (تعهد زمانی تیکت)، `automation`, `communication` | — |

---

## ۴. سیستم دسترسی فعلی (Existing Permission System)

- RBAC در `sec`: `roles` (درختی با `parent_role_id`)، `user_roles`، `user_module_roles`، `role_form_permissions` با ۷ اکشن (VIEW/CREATE/EDIT/DELETE/PRINT/EXPORT/**APPROVE**)، `role_field_permissions`، `role_menu_permissions`.
- اجرای واقعی: `roles.user_has_permission(user, company, form_code, action)` (`services/roles.py:295`) و `require_permission` در API. `is_super_admin` همیشه مجاز است.
- **شکاف‌ها:**
  - `user_has_permission` نه وراثت `parent_role_id` را حساب می‌کند، نه `user_module_roles` را (با `docs/permission-model.md` فاصله دارد).
  - `role_field_permissions` تعریف شده ولی **هیچ‌جا اعمال نمی‌شود** (فقط در پشتیبان‌گیری دیده می‌شود).
  - بسیاری از کنترل‌ها در لایهٔ UI هستند (`can(form, action)`)، نه سرویس.
  - مفهوم «مدیر» با نام نقش حدس زده می‌شود (`_MANAGER_ROLE_CODES`).
  - **ارتباط کاربر ↔ کارمند وجود ندارد** (`sec.users` و `hr.employees` به هم وصل نیستند)؛ پس مسیریابی «مدیر مستقیم» فعلاً ممکن نیست. `hr.organizational_units.manager_employee_id` و ساختار درختی واحدها وجود دارد.
  - دسترسی کاربر به انبار: `inv.warehouse_user_access` (برای مسیریابی بر اساس انبار قابل استفاده است).

---

## ۵. سیستم اعلان فعلی (Existing Notification System)

- جدول `sec.notifications` (migration 151) و سرویس `services/notifications.py`: `create_notification`, `notify_managers`, `list_notifications`, `mark_read`. CRM هم از طریق `crm/common.notify` همین را استفاده می‌کند.
- مصرف‌کننده: **فقط موبایل** (`routers/notifications.py` + `NotificationsScreen.tsx`).
- **دسکتاپ هیچ مرکز اعلانی ندارد** (نه زنگوله، نه فهرست، نه toast).
- کانال‌ها:
  - پیامک: `sms_gateway.py` و `crm/communication.SmsProvider`.
  - ایمیل: **زیرساخت وجود ندارد** (نه SMTP، نه تنظیمات).
  - Push موبایل: **وجود ندارد** (`expo-notifications` نصب نیست).
- ترجیحات اعلان کاربر وجود ندارد.

---

## ۶. سیستم حسابرسی فعلی (Existing Audit System)

- `audit.activity_log` با تریگر تغییرناپذیری (`006_audit_log.sql`)؛ `audit.log_activity(session, …)` **در همان تراکنش** عملیات اصلی (طراحی درست).
- محدودیت: CHECK روی `action` فقط `CREATE/UPDATE/DELETE/APPROVE/REVERSE/MERGE` را می‌پذیرد (`041_audit_log_merge_action.sql`). به همین دلیل CRM اکشن‌های ناشناخته را به `UPDATE` تبدیل می‌کند و نوع عملیات واقعی فقط در `changes` می‌ماند.
- API موبایل `peecha_api/audit_log.record` را **در session جدا** ثبت می‌کند (اتمیک نیست).
- صفحهٔ «امنیت (رخدادنگار)» برای جستجو وجود دارد (`ui/screens/audit_log.py`).
- جدول‌های `*_history` با تریگر برای تغییرات دسترسی‌ها.

---

## ۷. سیستم کار/کارتابل فعلی (Existing Task System)

**الف) موتور کارتابل `wf` (پایهٔ اصلی موتور تازه)** — `004_workflow_cartable.sql`, `db/models/workflow.py`, `services/cartable.py`:

- جدول‌ها:
  - تعریف: `approval_workflows` (به ازای فرم)، `approval_workflow_steps` (نقش تاییدکننده)، `approval_step_conditions` (فقط `AMOUNT_THRESHOLD`).
  - اجرا: `cartable_items`، `cartable_item_steps` (زنجیرهٔ ثابت‌شده برای هر درخواست — نسخه‌گذاری ضمنی)، `cartable_actions` (تاریخچه).
- `register_handler(form_code, on_approved, on_rejected, describe)` — مصرف‌کننده‌ها: سند حسابداری (`journal_entries.py:1188`) و ۸ عملیات دارایی (`fixed_assets/approval.py`).
- UI: «طراحی گردش کار» (`workflow_designer.py`، فقط زنجیرهٔ نقش‌ها) و «کارتابل من» (`my_tasks.py`).
- API: `/approvals` (+ approve/reject) و صفحهٔ موبایل `ApprovalsInboxScreen.tsx`.
- **ایرادهای فنی که باید رفع شوند:**
  1. `on_approved` **بعد از commit** کارتابل صدا زده می‌شود (`cartable.py`، `approve_item`). اگر اجرای سند خطا بدهد، آیتم «تاییدشده» می‌ماند ولی سند نهایی نمی‌شود — ناسازگاری.
  2. قفل ردیف یا کنترل نسخه ندارد؛ دو تاییدکنندهٔ هم‌زمان هر دو می‌توانند عبور کنند.
  3. جلوی خودتاییدی (Self-Approval) گرفته نمی‌شود.
  4. RETURN/DELEGATE/RESUBMIT و درخواست‌های EDIT/DELETE در enum هستند ولی پیاده نشده‌اند. تفویض تاریخ‌دار وجود ندارد.
  5. تاییدکننده فقط «نقش» است؛ موازی، «یکی از»، «همه» و درصدی پشتیبانی نمی‌شود.
  6. SLA، یادآوری، Escalation و اعلان وجود ندارد.
  7. ارسال سند حسابداری به کارتابل در **لایهٔ UI** انجام می‌شود (`journal_entries_list.py:421-432`)، نه سرویس.

**ب) کارهای عملیاتی** — `services/operational_tasks.py`: صف‌های موجود را جمع می‌کند (تصویب مدیر، رسید انبار، تایید تسویه، تبدیل به فاکتور، …) و در «کارتابل من» نشان می‌دهد. منطق تازه‌ای ندارد و فقط پرس‌وجو می‌کند.

**ج) کارهای CRM** — `crm.activities` (فعالیت/پیگیری با موعد)، مرکز کارها، `crm.sla_policies` برای تیکت.

**نتیجه:** سه صندوق جدا داریم (کارتابل wf، کارهای عملیاتی، فعالیت‌های CRM). «My Work» باید این سه را **یکجا** نشان دهد، نه اینکه صندوق چهارمی بسازد.

---

## ۸. لایهٔ API فعلی (Existing API Layer)

- قرارداد: یک روتر برای هر حوزه (`routers/*.py`)، پیشوند منبع (`/crm/...`، `/approvals`)، `AuthContext` با `user_id`/`company_id`، خطای سرویس (`ValueError`) به 400 فارسی تبدیل می‌شود، و `require_permission(form, action)`.
- Idempotency: `peecha_api/idempotency.run_idempotent` با جدول `sec.api_idempotency_keys` (هدر `Idempotency-Key`). روی `/approvals/.../approve` **استفاده نشده**.
- Rate limit: `rate_limit.py`. Webhook ورودی وجود ندارد.

---

## ۹. ساختار پایگاه‌داده (Existing Database Structure)

- اسکیمای `wf` از روز اول وجود دارد (۱۰ جدول بالا) — موتور تازه **در همین اسکیما** و افزایشی ساخته می‌شود.
- الگوی ارجاع نرم `form_id + source_record_id` (کارتابل، پیوست‌ها `005_attachments.sql`) — برای ارجاع Workflow به هر سند همین الگو به کار می‌رود.
- `sec.notifications`، `sec.api_idempotency_keys`، `audit.activity_log` و `inv.warehouse_user_access` وجود دارند.
- `comm.branches`، `hr.organizational_units` (دپارتمان، درختی، با مدیر) و مرکز هزینه به‌صورت تفصیلی (`cost_center_detail_account_id`) هم موجودند.
- تقویم کاری/تعطیلات: **وجود ندارد**. `prd` فقط ظرفیت شیفت دارد و `planning.calendar` نمایش است، نه تقویم کاری.
- آخرین migration: `209_crm_persian_labels.sql` → موتور از **210** شروع می‌شود.

---

## ۱۰. اجزای قابل استفادهٔ مجدد (Reusable Components)

| جزء | کاربرد در موتور |
|---|---|
| `wf.*` + `services/cartable.py` | پایهٔ داده و الگوی handler؛ از طریق «لایهٔ سازگاری» حفظ می‌شود |
| الگوی «دستور معوق» دارایی (`fixed_assets/approval.py`) | الگوی استاندارد «تایید، سپس اجرا با سرویس موجود» |
| قاعدهٔ JSON بخش مشتری (`crm/segments`: `{"all"/"any": [{field, op, value}]}`، عملگرها، ویرایشگر شرط در `SegmentDialog`) | پایهٔ Condition Engine و Rule Builder |
| `crm/automation` (Trigger/Action با `Param`، cooldown، preview) | پایهٔ «Scheduled Scan Trigger» و الگوی فرم پارامتر |
| `crm/communication` (Provider، `render` با جای‌نگهدار فارسی، `NotConfiguredProvider`) | کانال‌های اعلان (پیامک/ایمیل/…) |
| `crm/insights.RuleBasedProvider` | الگوی رابط AI-Ready (Provider قابل‌تعویض) |
| `notifications.py` / `sec.notifications` | اعلان درون‌برنامه‌ای |
| `audit.log_activity` | حسابرسی در همان تراکنش |
| `roles.user_has_permission`, `require_permission` | کنترل دسترسی |
| `run_idempotent` | Idempotency در API |
| موتور گزارش مشترک (`ReportDef`/`ReportResult`، `PurchaseReportScreen`) | گزارش‌های تحلیل Workflow |
| `module_style` (دکمه‌های آیکونی، کارت خلاصه، فوتر)، `FormDialog`، ظاهر `SectionStepper` (`widgets.py`) | UI یکدست؛ نوار وضعیت Workflow روی سند (ویجت تازهٔ `WorkflowStatusBar` با همان ظاهر) |
| الگوی تیک `QTimer` در پوسته | اجرای دوره‌ای Scheduler (با قفل پایگاه‌داده) |
| `with_for_update()` (در inventory/production/costing) | الگوی قفل ردیف برای هم‌زمانی |

---

## ۱۱. اجزایی که **نباید** تکرار شوند (Must NOT Be Duplicated)

1. **منطق تایید/ثبت اسناد**: Workflow هرگز وضعیت سند را مستقیم با SQL عوض نمی‌کند و فقط `approve_document`, `approve_request`, `approve_journal_entry`, … را صدا می‌زند.
2. **جدول اعلان دوم**: همان `sec.notifications` توسعه داده می‌شود.
3. **جدول حسابرسی دوم**: همان `audit.activity_log` (با بازکردن CHECK اکشن‌ها). لاگ اجرای فنی (Observability) جداست و جایگزین حسابرسی نیست.
4. **سیستم دسترسی دوم**: همان `sec.roles`/فرم‌ها/اکشن `APPROVE`.
5. **کارتابل دوم**: «کارتابل من» ارتقا می‌یابد و موارد قدیمی wf، کارهای عملیاتی، فعالیت‌های CRM و کارهای تازهٔ Workflow را یکجا نشان می‌دهد.
6. **موتور قاعدهٔ دوم برای CRM**: قاعده‌های CRM سر جای خود می‌مانند. Workflow برای فرایندهای چندمرحله‌ای است و ارزیاب شرط مشترک می‌شود.
7. **تعهد زمانی تیکت CRM** بازنویسی نمی‌شود. محاسبه‌گر تقویم کاری تازه بعداً می‌تواند به آن هم سرویس بدهد.
8. **Idempotency API**: همان `run_idempotent`.

---

## ۱۲. مدل‌های تازهٔ لازم (Required New Models) — همه در اسکیمای `wf`

**تعریف (Data-Driven، نسخه‌دار):**
- `wf.definitions` — شناسه، شرکت، کد، نام، ماژول، نوع موجودیت (`entity_type`)، وضعیت چرخهٔ عمر (`DRAFT/TESTING/PUBLISHED/ACTIVE/PAUSED/ARCHIVED`)، نسخهٔ فعال، دسته (برای قالب‌ها)، سازنده.
- `wf.definition_versions` — `version_no`، `graph JSONB` (گره‌ها و یال‌ها)، `checksum`، `published_at/by`، `is_immutable`. نسخهٔ منتشرشده هرگز ویرایش نمی‌شود؛ ویرایش یعنی نسخهٔ تازه.
- `wf.definition_triggers` — جدول جستجوی سریع: (`company_id`, `event_type`, `entity_type`) ← نسخه.
- `wf.templates` — قالب‌های آماده (Sales/Purchase/Finance/Inventory/HR/Production/CRM) به‌صورت داده.

**اجرا (Runtime، Restart-safe):**
- `wf.instances` — نسخهٔ تعریف، ارجاع نرم به سند (`entity_type`, `entity_id`, `form_id`)، وضعیت (`RUNNING/WAITING/COMPLETED/FAILED/CANCELLED/SUSPENDED`)، گره(های) جاری، `context JSONB` (تصویر لحظهٔ شروع)، `correlation_key UNIQUE` (جلوگیری از اجرای تکراری برای یک رویداد)، `row_version` (قفل خوش‌بینانه)، `depth` (جلوگیری از بازگشت بی‌نهایت)، زمان شروع و پایان.
- `wf.instance_steps` — لاگ اجرای هر گره: شروع/پایان/مدت/وضعیت/خطا/تعداد تلاش/قاعدهٔ ارزیابی‌شده و نتیجه (Observability + Timeline).
- `wf.tasks` — کار انسانی (Approval/Task/Review/Exception): نوع، عنوان، اولویت، حالت رأی (`SINGLE/ANY/ALL/PERCENT`، آستانه)، موعد، وضعیت تعهد زمانی، وضعیت، تصمیم نهایی، `row_version`.
- `wf.task_assignees` — نامزدهای حل‌شده (کاربر/نقش، منبع: مستقیم/تفویض/Escalation).
- `wf.task_decisions` — هر رأی/نظر/درخواست اصلاح (تغییرناپذیر).
- `wf.delegations` — از کاربر ← به کاربر، دامنه (همه/ماژول/فرم)، `valid_from/valid_to`، `revoked_at`، ثبت‌کننده.
- `wf.action_executions` — دفتر Idempotency: `idempotency_key UNIQUE`، نوع اقدام، وضعیت (`PENDING/DONE/FAILED`)، تلاش‌ها، `next_retry_at`، نتیجه.
- `wf.exceptions` — مالک، اولویت، علت (پیام فارسی + جزئیات فنی جدا)، وضعیت (`OPEN/RETRYING/RESOLVED/IGNORED/ESCALATED`).
- `wf.timers` — موعدها (Wait، یادآوری، Escalation، تعهد زمانی) با `due_at`، `status` و `locked_until` (اجرای امن چندکلاینتی).
- `wf.events` — **Transactional Outbox**: نوع رویداد، موجودیت، `payload`، `dedupe_key UNIQUE`، `processed_at`، تلاش‌ها.

**پیکربندی:**
- `wf.sla_policies`, `wf.escalation_rules` — به ازای اولویت/مرحله (۲۴ ساعت ← یادآوری، ۴۸ ← مدیر، ۷۲ ← Escalate).
- `wf.business_calendars`, `wf.calendar_hours` (ساعات کاری هر روز هفته)، `wf.holidays` (تعطیلات را ادمین وارد می‌کند؛ تعطیلات قمری قابل کدنویسی ثابت نیست)، و اتصال تقویم به شعبه/دپارتمان.
- `wf.notification_prefs` — کاربر × نوع اعلان × کانال (درون‌برنامه/دسکتاپ/پیامک/ایمیل/Push).

**افزودنی به جدول‌های موجود (فقط ستون nullable):**
- `hr.employees.user_id` — اتصال کاربر به کارمند برای مسیریابی «مدیر مستقیم/واحد».
- `sec.notifications`: ستون‌های `priority`، `action_url`/`task_id` (nullable).

---

## ۱۳. مهاجرت‌های لازم (Required Migrations)

همه **افزایشی** و نسخه‌دار، هرکدام با فایل برگشت در `db/rollback/`. بدون حذف یا تغییر نوع ستون موجود.

| شماره | محتوا |
|---|---|
| `210_wf_engine_core.sql` | definitions, versions, triggers, instances, instance_steps, events (outbox), action_executions, exceptions, timers + ایندکس‌ها |
| `211_wf_approvals.sql` | tasks, task_assignees, task_decisions, delegations؛ بازکردن CHECK اکشن‌های `audit.activity_log` (SUBMIT/REJECT/DELEGATE/ESCALATE/EXECUTE/…) |
| `212_wf_sla_calendar.sql` | sla_policies, escalation_rules, business_calendars, calendar_hours, holidays |
| `213_wf_notifications.sql` | notification_prefs + ستون‌های nullable `sec.notifications` |
| `214_wf_org_links.sql` | `hr.employees.user_id` (nullable، یکتا در شرکت) |
| `215_wf_templates_legacy.sql` | قالب‌ها + **انتقال داده‌ای** تعریف‌های فعال `wf.approval_workflows` به نسخهٔ ۱ تعریف تازه (موارد در جریان قدیمی دست نمی‌خورند) |

محافظت: قبل از اجرای migrationها روی دیتابیس واقعی، پشتیبان‌گیری موجود (`services/backup.py`) پیشنهاد/اجرا می‌شود. هر migration یک تست rollback و اجرای دوباره هم دارد.

---

## ۱۴. نقاط یکپارچگی (Integration Points)

**قرارداد مرکزی: Entity Adapter.** هر ماژول یک adapter ثبت می‌کند (مثل `register_handler` فعلی، ولی کامل‌تر):

```
EntityAdapter(
  entity_type="SALES_ORDER", form_code="commercial_document_sales_order", label="سفارش فروش",
  fields=…             # فهرست فیلدهای قابل‌استفاده در شرط/Rule Builder (نوع، برچسب فارسی، حساسیت)
  load_context(cid, id) -> dict     # مبلغ، مشتری، سقف اعتبار، مانده، اعتبار آزاد، اقلام، تخفیف، فروشنده، شعبه، انبار
  approval_context(cid, id) -> dict  # کارت «تصمیم بدون باز کردن چند صفحه»
  actions={ "approve": …approve_document, "reject": …, "release": … }  # فقط توابع سرویس موجود + سطح ریسک
  is_done(cid, id, action) -> bool   # برای Idempotency حالت‌محور
  owner(cid, id), open_link(id)
)
```

| ماژول | رویدادها (منتشر از سرویس موجود) | اقدام‌ها (سرویس موجود) | نمونه |
|---|---|---|---|
| فروش | `SalesOrderCreated/Confirmed/Approved`, `InvoicePosted`, `DiscountBelowMargin`, `CreditExceeded` | `approve_document`, `create/release_credit_hold`, `convert_to_invoice` | سفارش > سقف اعتبار ← مدیر فروش |
| خرید | `PurchaseRequestSubmitted`, `PurchaseOrderConfirmed`, `SupplierInvoiceCreated` | `approve_request/reject_request`, `approve_document` | سفارش خرید > ۵۰۰M ← مدیر ← مالی |
| خزانه/حسابداری | `PaymentVoucherCreated`, `JournalSubmitted`, `PaymentReceived` | `approve_journal_entry` (handler موجود) | پرداخت > آستانه ← مالی ← خزانه |
| انبار | `StockBelowMinimum` (Scan روی `reorder_point_qty`)، `StockDocumentConfirmed`, `TransferRequested`, `CountCompleted` | `confirm_stock_document`، ساخت درخواست خرید از حداقل موجودی (موجود) | موجودی < حداقل ← سفارش مجدد |
| تولید | `ProductionOrderPlanned/Released/Completed`, `MaterialShortage` | انتقال وضعیت در `production/orders`، `approve_plan` | بررسی مواد ← ظرفیت ← صدور |
| CRM | `LeadCreated`, `OpportunityWon`, `CustomerInactive` (Scan)، `TicketBreached` | `create_activity`, `assign`, `notify` (موجود) | فرصت برنده ← پیگیری |
| منابع انسانی/حقوق | `LoanRequested`, `PayrollRunCalculated`, `OvertimeRecorded`، **`LeaveRequested` (نیاز به موجودیت تازه)** | `approve_loan`, `approve_run` | مرخصی ← مدیر ← منابع انسانی |
| دارایی ثابت | ۸ عملیات حساس (`fixed_assets/approval.OPERATIONS`) | `_execute` موجود (اجرای سرویس دارایی) | واگذاری ← مدیر ← مالی |
| مشتری/تامین‌کننده | `CustomerSubmitted` (`PENDING_APPROVAL`) | `approve_customer/reject_customer` | مشتری جدید موبایل ← تایید |

**دروازهٔ تایید (Approval Gate):** پرچم‌های فعلی (`SALES_ORDER_MANAGER_APPROVAL`, …) **همچنان کار می‌کنند**. فقط وقتی برای همان موجودیت و گذار یک Workflow فعال منتشر شده باشد، سرویس به جای وضعیت‌های قدیمی از `workflow.gate(entity, transition)` تبعیت می‌کند (یک خط در هر سرویس، سازگار با گذشته).

**انتشار رویداد:** صریح و در همان تراکنش سرویس — `events.publish(session, "SalesOrderConfirmed", entity, payload)` در نقاط commit موجود (حداقل تغییر، یک خط). رویدادهای عمومی Created/Updated/StatusChanged فقط برای مدل‌های ثبت‌شده در Adapter، از طریق یک listener کنترل‌شده.

**ارسال از داخل سند:** دکمهٔ «ارسال برای تایید» و نوار وضعیت Workflow (`WorkflowStatusBar`، هم‌ظاهر با `SectionStepper`) به صفحه‌های سند اضافه می‌شود. منطق ارسال سند حسابداری از UI به سرویس منتقل می‌شود.

---

## ۱۵. ریسک‌های فنی (Technical Risks)

| # | ریسک | راه‌حل |
|---|---|---|
| T1 | سرویس‌ها session خودشان را باز می‌کنند؛ تراکنش سراسری بین Workflow و چند سرویس ممکن نیست. | هر گره یک تراکنش مستقل دارد. اقدام حساس: ۱) ردیف `action_executions` با کلید یکتا (commit)؛ ۲) صدا زدن سرویس (که خودش اتمیک است، مثل `post_document` برای انبار+دفتر)؛ ۳) ثبت نتیجه. پس از قطعی، `is_done` حالت سند را چک می‌کند و دوباره اجرا نمی‌کند. شکست ← Exception انسانی، نه دادهٔ نیمه‌کاره. |
| T2 | پس‌زمینهٔ سروری نداریم؛ `QTimer` فقط وقتی برنامه باز است، و چند کلاینت هم‌زمان ممکن است کاری را تکراری اجرا کنند. | `wf.timers`/`wf.events` با `FOR UPDATE SKIP LOCKED` و `locked_until`، به‌علاوهٔ کلید dedupe. اجراکننده‌ها: تیک دسکتاپ (۶۰ ثانیه)، حلقهٔ اختیاری در FastAPI، و فرمان مستقل `python -m peecha.workflow_worker` برای سرور. |
| T3 | ایرادهای کارتابل فعلی (handler پس از commit، بدون قفل، بدون منع خودتاییدی). | لایهٔ سازگاری در فاز ۱: API `cartable.*` حفظ و پیاده‌سازی امن جایگزین می‌شود. |
| T4 | تایید دوگانه: پرچم‌های ماژول و Workflow هم‌زمان. | قاعدهٔ «دروازهٔ واحد»: یک گذار، یک مالک (`workflow.gate`). اعتبارسنجی Publish تعارض را گزارش می‌دهد. |
| T5 | شکاف دسترسی (وراثت نقش، نقش ماژولی، سطح فیلد). | یک `authorize()` مرکزی که همان `user_has_permission` را صدا می‌زند و (در فاز ۲) وراثت را کامل می‌کند، بدون تغییر رفتار برای نقش‌های فعلی. |
| T6 | CHECK اکشن حسابرسی. | migration 211 فهرست را باز می‌کند (افزایشی). |
| T7 | تعریف به نقش/کاربر حذف‌شده یا فیلد تغییرکرده ارجاع دهد. | اعتبارسنجی هنگام Publish و هنگام اجرا؛ نبود تاییدکننده ← Exception به مالک فرایند. |
| T8 | پیچیدگی طراح گرافیکی در PySide6. | `QGraphicsScene` با چیدمان عمودی خودکار (بدون کشیدن آزاد پیچیده)، و Wizard به‌عنوان مسیر اصلی. |
| T9 | منطق در UI (ارسال سند حسابداری). | انتقال به سرویس در فاز ۵. |
| T10 | Workflow حلقه بسازد (اقدام ← رویداد ← همان Workflow). | `depth` و شمارندهٔ اجرا در instance، سقف اجرای هر گره، و منع شروع مجدد همان تعریف روی همان موجودیت در زنجیرهٔ علّی (`causation_id`). |

## ۱۶. ریسک‌های کارایی (Performance Risks)

| ریسک | راه‌حل |
|---|---|
| انتشار رویداد عملیات کاربر را کند کند | فقط یک INSERT در outbox درون تراکنش؛ پردازش بعد از commit (درون‌فرایندی و غیرهم‌زمان) یا در تیک بعدی. |
| ساخت context سنگین برای هر رویداد | `definition_triggers` اول فیلتر می‌کند (بدون Workflow منطبق، context ساخته نمی‌شود). context تنبل و کش‌شده در طول یک dispatch است. |
| پیمایش‌های دوره‌ای (معوق، حداقل موجودی، مشتری غیرفعال) روی کل داده | پرس‌وجوی ایندکس‌دار با پنجرهٔ افزایشی و کلید dedupe دوره‌ای (الگوی CRM). |
| صندوق کار و مانیتور | ایندکس‌های جزئی روی (`company_id`, `status`) و (`assignee`, `status`) و صفحه‌بندی. |
| رشد لاگ اجرا | ایندکس زمانی و امکان بایگانی دوره‌ای (پارتیشن فعلاً لازم نیست). |
| fan-out اعلان به نقش‌ها | محاسبهٔ یک‌بارهٔ نامزدها در `task_assignees` و درج دسته‌ای اعلان. |

## ۱۷. ریسک‌های امنیتی (Security Risks)

| ریسک | راه‌حل |
|---|---|
| خودتاییدی | سیاست SoD در سطح تعریف (پیش‌فرض: ممنوع برای صادرکننده)، بررسی در سرویس (نه UI). |
| تایید بدون مجوز (API/موبایل) | هنگام تصمیم: نامزد بودن (یا تفویض معتبر) **و** داشتن `APPROVE` روی فرم، هر دو بررسی می‌شوند. |
| سوءاستفاده از تفویض | تاریخ‌دار، قابل لغو، حسابرسی‌شده، بدون تفویض زنجیره‌ای (مگر با اجازه)، فقط در دامنهٔ اختیار تفویض‌کننده. |
| اقدام خودکار بیش از حد اختیار | هر اقدام با «هویت اجرا» ثبت می‌شود (کاربر شروع‌کننده یا کاربر سیستمی با دسترسی صریح) و همیشه از سرویس موجود با همان اعتبارسنجی‌ها می‌گذرد. اقدام پرریسک (مالی/موجودی/حقوق/پرداخت) بدون گره تایید انسانی قبلی **قابل انتشار نیست**. |
| ویرایش تعریف‌ها | فرم دسترسی تازه `workflow_admin` و حسابرسی هر انتشار/توقف. |
| افشای فیلد حساس در Context تایید (بها، حاشیهٔ سود، حقوق، سقف اعتبار) | فیلدهای حساس در Adapter علامت می‌خورند و فقط با دسترسی فرم مربوط نمایش داده می‌شوند (و در صورت فعال‌سازی، `role_field_permissions`). |
| Webhook / رویداد خارجی | امضای HMAC، rate limit موجود، و dedupe. |
| تکرار/بازپخش درخواست | `Idempotency-Key` روی همهٔ POSTهای تصمیم + `row_version`. |
| AI | فقط پیشنهاد؛ هیچ مسیری برای اجرای مستقیم وجود ندارد. خروجی AI همیشه «پیش‌نویس» است و به تایید انسانی و Publish نیاز دارد. |
| موبایل | احراز هویت مجدد (step-up) برای تاییدهای حساس با endpoint کوتاه‌عمر؛ بیومتریک بعداً. |

---

## ۱۸. معماری پیشنهادی (Recommended Architecture)

```
 سرویس‌های موجود پیچا ──publish (همان تراکنش)──► wf.events (Outbox)
        ▲                                              │
        │ actions (فقط توابع سرویس)                     ▼
 ┌──────┴───────────────────────────────────────────────────────┐
 │                Workflow Engine  (src/peecha/services/workflow/) │
 │  registry.py   Entity Adapters + Action/Resolver plugins        │
 │  events.py     In-Process Event Bus + Outbox dispatcher         │
 │  conditions.py ارزیاب AST (all/any/not، فیلد‌به‌فیلد، تاریخ)     │
 │  definitions.py چرخهٔ عمر + نسخه + اعتبارسنجی گراف               │
 │  runtime.py    اجرای گره‌ها (هر گره یک تراکنش، قفل instance)     │
 │  approvals.py  SINGLE/ANY/ALL/PERCENT، ترتیبی/موازی، مسیریابی، SoD│
 │  routing.py    کاربر/نقش/دپارتمان/شعبه/مدیر/انبار/آستانه/پویا    │
 │  sla.py        تقویم کاری، موعد، یادآوری، Escalation              │
 │  scheduler.py  wf.timers + scans (SKIP LOCKED)                  │
 │  actions.py    اقدام‌های داخلی امن + اقدام‌های Adapter + Retry     │
 │  exceptions.py مدیریت استثنا                                     │
 │  inbox.py      My Work یکپارچه (wf + کارتابل قدیم + عملیاتی + CRM)│
 │  simulate.py   Test/Dry-Run (بدون نوشتن در دادهٔ عملیاتی)         │
 │  ai.py         SuggestionProvider (NullProvider پیش‌فرض)          │
 └──────┬───────────────────────────────────────────────────────┘
        │ notify / audit (همان تراکنش) / اعلان
        ▼
 sec.notifications  ·  audit.activity_log  ·  sms_gateway  ·  (ایمیل/Push: رابط)
```

**اصول کلیدی:**
1. **Orchestration, not Replacement:** موتور فقط تصمیم می‌گیرد «چه کسی، کی، چه سرویسی» و اجرای کسب‌وکار همیشه با سرویس موجود است.
2. **Event-Driven + Rule-Based + Human-in-the-Loop:** رویداد ← شرط ← تصمیم ← (تایید انسانی برای پرریسک) ← اجرا.
3. **ماندگار و Restart-safe:** هیچ حالت فقط در حافظه نیست. هر گره پس از commit پیش می‌رود و Scheduler از روی DB ادامه می‌دهد.
4. **نسخهٔ تغییرناپذیر:** هر instance به `definition_version_id` خودش قفل است.
5. **سازگاری کامل با گذشته:** `cartable.register_handler/submit_for_approval/approve_item/reject_item` و `/approvals` همان امضا را حفظ می‌کنند. کارهای در جریان قدیمی تا پایان روی جدول‌های قدیمی می‌مانند.
6. **دو سطح UI:** Wizard ساده (۸ مرحله) برای کاربر کسب‌وکار و طراح گرافیکی برای ادمین. «کارتابل من» و «مرکز تایید» برای همه.
7. **AI-Ready بدون وابستگی:** رابط Provider با پیاده‌سازی تهی، خروجی فقط پیش‌نویس.

**گره‌های گراف:** `START(Trigger)`, `CONDITION` (شاخه‌ای بله/خیر)، `APPROVAL`، `TASK`، `ACTION`، `NOTIFY`، `WAIT` (مدت/تا تاریخ/تا رویداد)، `PARALLEL` (انشعاب و اتصال)، `EXCEPTION` (مسیر خطا)، `END`.

**قواعد اعتبارسنجی Publish:** نبود Trigger/پایان، گره دست‌نیافتنی، حلقه بدون WAIT، تایید بدون تاییدکنندهٔ قابل‌حل، نقش یا کاربر نامعتبر، شرط با فیلد ناشناخته یا نوع ناسازگار، اقدام پرریسک بدون تایید قبلی، و تعارض دروازه با Workflow فعال دیگر.

**مرکز تایید و کار سریع:** کارت Context از `approval_context()` Adapter، دکمه‌های ✓ و ✕، درخواست اصلاح، تفویض و نظر. رنگ‌بندی فوری/امروز/این هفته از روی موعد تعهد زمانی است.

**نوار وضعیت روی سند:** `WorkflowStatusBar` (● انجام‌شده / ○ مانده) + Timeline از `instance_steps` و `task_decisions`.

---

## ۱۹. فازهای دقیق اجرا (Exact Implementation Phases)

هر فاز = یک نسخه (R###) با migration، تست `test_rNNN_*`، رگرسیون کامل، تحویل zip. بعد از هر فاز رگرسیون کل پیچا اجرا می‌شود.

| فاز | نسخه | محتوا | خروجی قابل‌لمس |
|---|---|---|---|
| ۱ — هسته | R291 | migration 210، `registry`, `events` (Outbox + dispatcher)، `conditions` (عمومی‌سازی قاعدهٔ بخش مشتری)، `definitions` (چرخهٔ عمر/نسخه/اعتبارسنجی)، `runtime`, `actions` (داخلی + Idempotency + Retry)، `scheduler` (timers + SKIP LOCKED + تیک دسکتاپ)، Exception، **لایهٔ سازگاری کارتابل** (رفع T3: اتمیک، قفل، SoD) | تعریف داده‌ای، اجرای Dry-Run از کد، کارتابل قدیمی امن‌تر |
| ۲ — تایید | R292 | migration 211، SINGLE/ANY/ALL/PERCENT، ترتیبی/موازی، مسیریابی (کاربر/نقش/دپارتمان/شعبه/انبار/آستانه/پویا/مدیر)، تفویض تاریخ‌دار، Request Changes/Return/Resubmit، هم‌زمانی (`row_version`)، SoD، حسابرسی | زنجیره‌های تایید واقعی |
| ۳ — کار و تعهد زمانی | R293 | migration 212–214، تقویم کاری/تعطیلات، تعهد زمانی، یادآوری، Escalation، **My Work** یکپارچه، **مرکز تایید** با تایید سریع، **مرکز اعلان دسکتاپ**، ترجیحات اعلان (درون‌برنامه/دسکتاپ/پیامک؛ ایمیل/Push به‌صورت رابط) | صندوق کار و اعلان |
| ۴ — طراح | R294 | Workflow Studio: فهرست/چرخهٔ عمر، **Wizard ۸ مرحله‌ای**، **Rule Builder** (WHEN/AND/THEN)، **طراح گرافیکی**، اعتبارسنجی، شبیه‌سازی با دادهٔ آزمایشی، Dry-Run روی سند واقعی | ساخت بی‌کد |
| ۵ — اتصال ERP | R295–R296 | Adapterها: فروش، خرید، خزانه/حسابداری، انبار، تولید، CRM، حقوق، دارایی، مشتری/تامین‌کننده؛ دروازهٔ تایید؛ دکمهٔ «ارسال برای تایید» و نوار وضعیت در اسناد؛ migration 215 (قالب‌ها + انتقال تعریف‌های قدیمی)؛ موجودیت حداقلی مرخصی (در صورت تایید) | ۲۳ قالب آماده و ۱۰ سناریوی پذیرش |
| ۶ — پایش | R297 | مانیتور (در جریان/منتظر/کامل/ناموفق/لغو/Escalate)، لاگ اجرا، تشخیص گلوگاه (زمان هر مرحله، ٪ بیش از تعهد زمانی)، تحلیل شکست و رد، گزارش‌ها روی موتور گزارش مشترک | داشبورد مدیر |
| ۷ — موبایل | R298 | `/workflow/*` با Idempotency و دسترسی، صندوق یکپارچه، کارت Context، تایید/رد/نظر/تفویض، احراز هویت مجدد برای موارد حساس | تایید از موبایل |
| ۸ — AI-Ready | R299 | رابط‌های `SuggestionProvider` (مسیریابی، طبقه‌بندی، خلاصه، استخراج سند، NL ← پیش‌نویس Workflow) با `NullProvider`، مسیر «پیش‌نویس ← اعتبارسنجی ← پیش‌نمایش ← تایید کاربر ← انتشار» | آمادهٔ اتصال AI، بدون وابستگی |

**API (قرارداد پیچا، روتر `src/peecha_api/routers/workflow.py`، پیشوند `/workflow`):**
`GET /workflow/inbox`، `GET /workflow/tasks/{id}` (با Context)، `POST /workflow/tasks/{id}/approve|reject|request-changes|delegate|comment` (با `Idempotency-Key`)، `POST /workflow/instances` (ارسال دستی)، `GET /workflow/instances?entity_type=&entity_id=`، `GET /workflow/instances/{id}/timeline`، `GET /workflow/definitions` (ادمین)، `POST /workflow/events` (یکپارچه‌سازی، HMAC). مسیرهای فعلی `/approvals` بدون تغییر ادامه می‌دهند.

---

## ۲۰. آزمون‌های پذیرش (Acceptance Tests)

**واحد/هسته** (`test_r291_*`): trigger و dedupe، شرط (AND/OR/NOT، فیلد‌به‌فیلد، تاریخ)، اعتبارسنجی گراف (۹ خطای بند ۵۶)، چرخهٔ عمر و نسخه (instance روی نسخهٔ خودش)، Retry با سقف، Idempotency (کلید تکراری ← بدون اجرای دوباره)، محافظت از حلقه، Dry-Run بدون نوشتن.

**تایید** (`test_r292_*`): تک/ترتیبی/موازی/یکی‌از/همه/درصدی، مسیریابی آستانه‌ای (`<100M`، `100M–500M`، `>500M`)، تفویض تاریخ‌دار و لغو، Request Changes ← Resubmit، دو تصمیم هم‌زمان (فقط یکی ثبت می‌شود).

**تعهد زمانی** (`test_r293_*`): موعد با تقویم کاری (شنبه–چهارشنبه ۸–۱۶، پنجشنبه ۸–۱۳، تعطیلات)، یادآوری ۲۴ ساعت، مدیر ۴۸ ساعت، Escalate ۷۲ ساعت، صندوق کار (فوری/امروز/هفته).

**یکپارچگی** (`test_r295_*`/`test_r296_*`): فروش، خرید، خزانه، انبار، CRM، منابع انسانی، حقوق، تولید، دارایی — هر کدام با سرویس واقعی و دادهٔ fixture.

**سناریوهای پذیرش (بند ۷۰):**
1. سفارش خرید > ۵۰۰M ← مدیر ← مالی ← سفارش «APPROVED» با `approve_document` واقعی.
2. تخفیف بیش از حد مجاز (زیر حاشیه) ← مدیر فروش.
3. فاکتور معوق ← کار وصول ← اعلان.
4. موجودی < حداقل ← Workflow سفارش مجدد (درخواست خرید از سرویس موجود).
5. مرخصی ← مدیر ← منابع انسانی ← تایید (پس از ساخت موجودیت مرخصی).
6. پرداخت ← مالی ← خزانه ← سند دائم (`approve_journal_entry`).
7. پایان مهلت ← یادآوری ← Escalation.
8. شکست اقدام ← Retry ← Exception ← حل انسانی.
9. رویداد تکراری ← **هیچ** سند/پرداخت/سند حسابداری تکراری ساخته نمی‌شود.
10. «ری‌استارت»: instance منتظر بعد از ساخت engine و session تازه درست ادامه می‌دهد (شبیه‌سازی ری‌استارت در تست).

**امنیت (بند ۷۱):** تایید سند بدون مجوز ← 403/خطا؛ خودتاییدی ممنوع؛ تفویض خارج از تاریخ بی‌اثر؛ Workflow نمی‌تواند سرویس یا دسترسی را دور بزند (اقدام پرریسک بدون تایید ← Publish رد می‌شود)؛ هر تایید در `audit.activity_log`؛ هر اقدام خودکار در `instance_steps`/`action_executions` قابل ردیابی است.

**قابلیت اطمینان:** ری‌استارت، Retry، رویداد تکراری، تصمیم هم‌زمان، و دو اجراکنندهٔ Scheduler هم‌زمان (بدون اجرای دوباره به لطف SKIP LOCKED).

**رگرسیون:** بعد از هر فاز `tests/integration/run_all.sh` کامل + smoke همهٔ صفحه‌ها + موبایل (`typecheck`/`test`) در فاز ۷.

---

## تصمیم‌هایی که پیش از فاز ۱ تایید شما را لازم دارند

1. **درخواست مرخصی**: در منابع انسانی چنین موجودیتی وجود ندارد. پیشنهاد: یک موجودیت حداقلی `hr.leave_requests` (نوع، از/تا، مدت، توضیح، وضعیت) در فاز ۵ ساخته شود تا سناریوی ۵ واقعی باشد.
2. **ایمیل و Push موبایل**: زیرساختی ندارند. پیشنهاد: فاز ۳ با درون‌برنامه + دسکتاپ + پیامک (موجود) و رابط آمادهٔ ایمیل/Push. تنظیم SMTP و `expo-notifications` در مرحلهٔ جدا (نیاز به `npm install` در موبایل).
3. **اجراکنندهٔ پس‌زمینه**: پیشنهاد هر سه مسیر — تیک دسکتاپ (پیش‌فرض)، حلقهٔ اختیاری در API، فرمان مستقل `workflow_worker` برای سرور — همه امن در برابر اجرای هم‌زمان.
4. **اتصال کاربر به کارمند** (`hr.employees.user_id`) برای مسیریابی «مدیر مستقیم/مدیر واحد».
5. **پرچم‌های تایید فعلی ماژول‌ها** حفظ شوند و Workflow فقط وقتی فعال و منتشر شده باشد جایگزین آن گذار شود (پیشنهاد: بله).
