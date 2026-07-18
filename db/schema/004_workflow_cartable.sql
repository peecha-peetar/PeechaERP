-- پیچا | کارتابل: صف تایید سراسری برای اسناد همه‌ی ماژول‌ها (حسابداری، انبار،
-- خرید و فروش، خزانه‌داری، ...)؛ هر سند از هر ماژول با ارجاع به sec.forms
-- (کاتالوگ فرم‌های موجود) و یک شناسه‌ی رکورد مبدا در این صف قرار می‌گیرد.
-- شامل: تایید چندمرحله‌ای، مسیریابی شرطی قابل‌گسترش، برگشت به کارتابل
-- صادرکننده، و درخواست حذف (حذف اسناد دائم هم از همین کارتابل عبور می‌کند).
-- PostgreSQL 13+ — شناسه‌ها snake_case هستند (بدون کوتیشن)
-- پیش‌نیاز: 002_security_rbac.sql

CREATE SCHEMA wf;

-- نوع درخواست: همان زیرساخت کارتابل هم برای تایید ثبت/ویرایش و هم برای
-- تایید درخواست حذف استفاده می‌شود؛ سرویس مصرف‌کننده (مثلاً حسابداری) با
-- توجه به request_type_id تصمیم می‌گیرد که APPROVED یعنی «دائم کن» یا «حذف کن».
CREATE TABLE wf.cartable_request_types (
    request_type_id SMALLINT    NOT NULL PRIMARY KEY,
    code             VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO wf.cartable_request_types (request_type_id, code) VALUES
    (1, 'CREATE'), (2, 'EDIT'), (3, 'DELETE');

CREATE TABLE wf.cartable_statuses (
    status_id SMALLINT    NOT NULL PRIMARY KEY,
    code      VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO wf.cartable_statuses (status_id, code) VALUES
    (1, 'PENDING'), (2, 'APPROVED'), (3, 'REJECTED'), (4, 'CANCELLED');
-- توجه: «عودت» (RETURN) یک وضعیت پایانی جدا نیست؛ آیتم PENDING می‌ماند ولی
-- current_approver_user_id آن به submitted_by_user_id تغییر می‌کند (یعنی به
-- کارتابل صادرکننده برمی‌گردد). با اقدام RESUBMIT دوباره به تاییدکننده‌ی همان مرحله می‌رود.

CREATE TABLE wf.cartable_action_types (
    action_type_id SMALLINT    NOT NULL PRIMARY KEY,
    code            VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO wf.cartable_action_types (action_type_id, code) VALUES
    (1, 'APPROVE'), (2, 'REJECT'), (3, 'RETURN'), (4, 'CANCEL'), (5, 'DELEGATE'), (6, 'RESUBMIT');

-- تعریف زنجیره‌ی تایید برای یک نوع سند مشخص در یک شرکت (اختیاری؛ نبودِ
-- تعریف یعنی تک‌مرحله‌ای با تاییدکننده‌ای که لایه‌ی سرویس مشخص می‌کند)
CREATE TABLE wf.approval_workflows (
    workflow_id INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id  INT         NOT NULL REFERENCES core.companies(company_id),
    form_id     INT         NOT NULL REFERENCES sec.forms(form_id),
    code        VARCHAR(50) NOT NULL,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_approval_workflows UNIQUE (company_id, form_id, code)
);

-- هر مرحله می‌تواند مخصوص یک نوع درخواست باشد (مثلاً زنجیره‌ی تایید حذف
-- می‌تواند از زنجیره‌ی تایید ثبت عادی سخت‌گیرتر/متفاوت باشد)
CREATE TABLE wf.approval_workflow_steps (
    workflow_id      INT      NOT NULL REFERENCES wf.approval_workflows(workflow_id),
    request_type_id  SMALLINT NOT NULL REFERENCES wf.cartable_request_types(request_type_id),
    step_no          SMALLINT NOT NULL,
    approver_role_id INT      NOT NULL REFERENCES sec.roles(role_id),   -- هر کاربرِ دارای این نقش می‌تواند این مرحله را تایید کند
    CONSTRAINT pk_approval_workflow_steps PRIMARY KEY (workflow_id, request_type_id, step_no)
);

-- ---------------------------------------------------------------------
-- قوانین شرطی مرحله‌ی تایید: یک مرحله می‌تواند «همیشه» اعمال شود (پیش‌فرض،
-- وقتی هیچ شرطی برایش ثبت نشده) یا فقط وقتی شرط(های) پیوست‌شده برقرار باشد
-- (مثلاً «فقط اگر مبلغ سند >= ۱۰۰,۰۰۰,۰۰۰ ریال»). چند شرط روی یک مرحله = AND.
-- نوع شرط از یک lookup می‌آید و پارامترهایش در JSONB است تا افزودن نوع شرط
-- جدید (مثلاً بر اساس مرکز هزینه یا حساب خاص) بدون تغییر ساختار جدول ممکن
-- باشد — فقط یک ردیف جدید در condition_types + یک ارزیاب در سرویس پایتون.
-- چون این جدول‌ها زیرمجموعه‌ی wf.approval_workflows هستند که خودشان به
-- form_id/ماژول وصل‌اند، این قوانین طبیعتاً «به‌تفکیک هر ماژول» تعریف/مدیریت
-- می‌شوند (در تنظیمات همان ماژول در UI).
-- ---------------------------------------------------------------------
CREATE TABLE wf.condition_types (
    condition_type_id SMALLINT    NOT NULL PRIMARY KEY,
    code               VARCHAR(30) NOT NULL UNIQUE
);
INSERT INTO wf.condition_types (condition_type_id, code) VALUES
    (1, 'AMOUNT_THRESHOLD');

CREATE TABLE wf.approval_step_conditions (
    condition_id      BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workflow_id        INT      NOT NULL,
    request_type_id    SMALLINT NOT NULL,
    step_no            SMALLINT NOT NULL,
    condition_type_id  SMALLINT NOT NULL REFERENCES wf.condition_types(condition_type_id),
    parameters          JSONB   NOT NULL DEFAULT '{}'::jsonb,  -- مثلاً {"operator": ">=", "amount": 100000000, "currency": "IRR"}
    CONSTRAINT fk_approval_step_conditions_step FOREIGN KEY (workflow_id, request_type_id, step_no)
        REFERENCES wf.approval_workflow_steps(workflow_id, request_type_id, step_no)
);
CREATE INDEX ix_approval_step_conditions_step ON wf.approval_step_conditions(workflow_id, request_type_id, step_no);

-- وضعیت زنده‌ی هر درخواست در کارتابل (یک سند در هر لحظه حداکثر یک درخواست PENDING دارد)
CREATE TABLE wf.cartable_items (
    cartable_item_id       BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id              INT         NOT NULL REFERENCES core.companies(company_id),
    form_id                  INT        NOT NULL REFERENCES sec.forms(form_id),   -- نوع سند (مثلاً «سند حسابداری»، «حواله انبار»، ...)
    source_record_id         BIGINT     NOT NULL,   -- کلید رکورد واقعی در جدول همان ماژول (مثلاً acc.journal_entries.journal_entry_id)؛ چون نوع منبع متغیر است، FK واقعی امکان‌پذیر نیست
    request_type_id          SMALLINT   NOT NULL REFERENCES wf.cartable_request_types(request_type_id),
    workflow_id              INT        NULL REFERENCES wf.approval_workflows(workflow_id),
    current_step_no          SMALLINT   NOT NULL DEFAULT 1,   -- به wf.cartable_item_steps همین آیتم اشاره دارد، نه مستقیم به قالب wf.approval_workflow_steps
    current_approver_role_id INT        NULL REFERENCES sec.roles(role_id),   -- کپی از تعریف مرحله، برای کوئری سریع صف کارتابل
    current_approver_user_id INT        NULL REFERENCES sec.users(user_id),   -- ارجاع مستقیم/تفویض‌شده؛ یا submitted_by_user_id وقتی «عودت» شده
    status_id                SMALLINT   NOT NULL REFERENCES wf.cartable_statuses(status_id),
    submitted_by_user_id     INT        NOT NULL REFERENCES sec.users(user_id),
    submitted_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_cartable_items_source ON wf.cartable_items(form_id, source_record_id);
-- صف «کارهای من»: جست‌وجوی سریع موارد PENDING به‌ازای نقش/کاربر جاری
CREATE INDEX ix_cartable_items_pending_by_role ON wf.cartable_items(current_approver_role_id, status_id) WHERE status_id = 1;
CREATE INDEX ix_cartable_items_pending_by_user ON wf.cartable_items(current_approver_user_id, status_id) WHERE status_id = 1;

-- زنجیره‌ی نهاییِ محقق‌شده برای همین درخواست خاص: در لحظه‌ی ارسال، سرویس
-- پایتون شرط‌های wf.approval_step_conditions را در برابر اطلاعات همان سند
-- (مثلاً مبلغ کل) ارزیابی می‌کند و فقط مراحلِ منطبق (یا بدون‌شرط) را اینجا
-- ماده‌ی می‌کند و پیاپی شماره‌گذاری می‌کند. با این کار زنجیره‌ی واقعیِ طی‌شده
-- برای هر سند شفاف/قابل‌حسابرسی می‌ماند، حتی اگر بعداً تعریف قوانین در
-- wf.approval_workflow_steps تغییر کند.
CREATE TABLE wf.cartable_item_steps (
    cartable_item_id BIGINT   NOT NULL REFERENCES wf.cartable_items(cartable_item_id),
    step_no          SMALLINT NOT NULL,
    approver_role_id INT      NOT NULL REFERENCES sec.roles(role_id),
    CONSTRAINT pk_cartable_item_steps PRIMARY KEY (cartable_item_id, step_no)
);

-- تاریخچه‌ی کامل اقدامات روی هر آیتم کارتابل (تایید/رد/عودت/ابطال/ارجاع/ارسال‌مجدد)
CREATE TABLE wf.cartable_actions (
    action_id        BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cartable_item_id  BIGINT      NOT NULL REFERENCES wf.cartable_items(cartable_item_id),
    step_no           SMALLINT    NOT NULL,
    action_type_id     SMALLINT   NOT NULL REFERENCES wf.cartable_action_types(action_type_id),
    action_by_user_id  INT        NOT NULL REFERENCES sec.users(user_id),
    comment            TEXT       NULL,
    action_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_cartable_actions_item ON wf.cartable_actions(cartable_item_id);
