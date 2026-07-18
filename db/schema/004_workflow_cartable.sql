-- پیچا | کارتابل: صف تایید سراسری برای اسناد همه‌ی ماژول‌ها (حسابداری، انبار،
-- خرید و فروش، خزانه‌داری، ...)؛ هر سند از هر ماژول با ارجاع به sec.Forms
-- (کاتالوگ فرم‌های موجود) و یک شناسه‌ی رکورد مبدا در این صف قرار می‌گیرد.
-- شامل: تایید چندمرحله‌ای، برگشت به کارتابل صادرکننده، و درخواست حذف
-- (حذف اسناد دائم هم از همین کارتابل عبور می‌کند، نه حذف مستقیم).
-- PostgreSQL 13+
-- پیش‌نیاز: 002_security_rbac.sql

CREATE SCHEMA wf;

-- نوع درخواست: همان زیرساخت کارتابل هم برای تایید ثبت/ویرایش و هم برای
-- تایید درخواست حذف استفاده می‌شود؛ سرویس مصرف‌کننده (مثلاً حسابداری) با
-- توجه به RequestTypeID تصمیم می‌گیرد که APPROVED یعنی «دائم کن» یا «حذف کن».
CREATE TABLE wf.CartableRequestTypes (
    RequestTypeID SMALLINT    NOT NULL PRIMARY KEY,
    Code          VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO wf.CartableRequestTypes (RequestTypeID, Code) VALUES
    (1, 'CREATE'), (2, 'EDIT'), (3, 'DELETE');

CREATE TABLE wf.CartableStatuses (
    StatusID SMALLINT    NOT NULL PRIMARY KEY,
    Code     VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO wf.CartableStatuses (StatusID, Code) VALUES
    (1, 'PENDING'), (2, 'APPROVED'), (3, 'REJECTED'), (4, 'CANCELLED');
-- توجه: «عودت» (RETURN) یک وضعیت پایانی جدا نیست؛ آیتم PENDING می‌ماند ولی
-- CurrentApproverUserID آن به SubmittedByUserID تغییر می‌کند (یعنی به کارتابل
-- صادرکننده برمی‌گردد). با اقدام RESUBMIT دوباره به تاییدکننده‌ی همان مرحله می‌رود.

CREATE TABLE wf.CartableActionTypes (
    ActionTypeID SMALLINT    NOT NULL PRIMARY KEY,
    Code         VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO wf.CartableActionTypes (ActionTypeID, Code) VALUES
    (1, 'APPROVE'), (2, 'REJECT'), (3, 'RETURN'), (4, 'CANCEL'), (5, 'DELEGATE'), (6, 'RESUBMIT');

-- تعریف زنجیره‌ی تایید برای یک نوع سند مشخص در یک شرکت (اختیاری؛ نبودِ
-- تعریف یعنی تک‌مرحله‌ای با تاییدکننده‌ای که لایه‌ی سرویس مشخص می‌کند)
CREATE TABLE wf.ApprovalWorkflows (
    WorkflowID INT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    CompanyID  INT         NOT NULL REFERENCES core.Companies(CompanyID),
    FormID     INT         NOT NULL REFERENCES sec.Forms(FormID),
    Code       VARCHAR(50) NOT NULL,
    IsActive   BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT UQ_ApprovalWorkflows UNIQUE (CompanyID, FormID, Code)
);

-- هر مرحله می‌تواند مخصوص یک نوع درخواست باشد (مثلاً زنجیره‌ی تایید حذف
-- می‌تواند از زنجیره‌ی تایید ثبت عادی سخت‌گیرتر/متفاوت باشد)
CREATE TABLE wf.ApprovalWorkflowSteps (
    WorkflowID     INT      NOT NULL REFERENCES wf.ApprovalWorkflows(WorkflowID),
    RequestTypeID  SMALLINT NOT NULL REFERENCES wf.CartableRequestTypes(RequestTypeID),
    StepNo         SMALLINT NOT NULL,
    ApproverRoleID INT      NOT NULL REFERENCES sec.Roles(RoleID),   -- هر کاربرِ دارای این نقش می‌تواند این مرحله را تایید کند
    CONSTRAINT PK_ApprovalWorkflowSteps PRIMARY KEY (WorkflowID, RequestTypeID, StepNo)
);

-- ---------------------------------------------------------------------
-- قوانین شرطی مرحله‌ی تایید: یک مرحله می‌تواند «همیشه» اعمال شود (پیش‌فرض،
-- وقتی هیچ شرطی برایش ثبت نشده) یا فقط وقتی شرط(های) پیوست‌شده برقرار باشد
-- (مثلاً «فقط اگر مبلغ سند >= ۱۰۰,۰۰۰,۰۰۰ ریال»). چند شرط روی یک مرحله = AND.
-- نوع شرط از یک lookup می‌آید و پارامترهایش در JSONB است تا افزودن نوع شرط
-- جدید (مثلاً بر اساس مرکز هزینه یا حساب خاص) بدون تغییر ساختار جدول ممکن
-- باشد — فقط یک ردیف جدید در ConditionTypes + یک ارزیاب در سرویس پایتون.
-- چون این جدول‌ها زیرمجموعه‌ی wf.ApprovalWorkflows هستند که خودشان به
-- FormID/ماژول وصل‌اند، این قوانین طبیعتاً «به‌تفکیک هر ماژول» تعریف/مدیریت
-- می‌شوند (در تنظیمات همان ماژول در UI).
-- ---------------------------------------------------------------------
CREATE TABLE wf.ConditionTypes (
    ConditionTypeID SMALLINT    NOT NULL PRIMARY KEY,
    Code            VARCHAR(30) NOT NULL UNIQUE
);
INSERT INTO wf.ConditionTypes (ConditionTypeID, Code) VALUES
    (1, 'AMOUNT_THRESHOLD');

CREATE TABLE wf.ApprovalStepConditions (
    ConditionID     BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    WorkflowID      INT      NOT NULL,
    RequestTypeID   SMALLINT NOT NULL,
    StepNo          SMALLINT NOT NULL,
    ConditionTypeID SMALLINT NOT NULL REFERENCES wf.ConditionTypes(ConditionTypeID),
    Parameters      JSONB    NOT NULL DEFAULT '{}'::jsonb,  -- مثلاً {"operator": ">=", "amount": 100000000, "currency": "IRR"}
    CONSTRAINT FK_ApprovalStepConditions_Step FOREIGN KEY (WorkflowID, RequestTypeID, StepNo)
        REFERENCES wf.ApprovalWorkflowSteps(WorkflowID, RequestTypeID, StepNo)
);
CREATE INDEX IX_ApprovalStepConditions_Step ON wf.ApprovalStepConditions(WorkflowID, RequestTypeID, StepNo);

-- وضعیت زنده‌ی هر درخواست در کارتابل (یک سند در هر لحظه حداکثر یک درخواست PENDING دارد)
CREATE TABLE wf.CartableItems (
    CartableItemID         BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    CompanyID               INT          NOT NULL REFERENCES core.Companies(CompanyID),
    FormID                   INT          NOT NULL REFERENCES sec.Forms(FormID),   -- نوع سند (مثلاً «سند حسابداری»، «حواله انبار»، ...)
    SourceRecordID           BIGINT       NOT NULL,   -- کلید رکورد واقعی در جدول همان ماژول (مثلاً acc.JournalEntries.JournalEntryID)؛ چون نوع منبع متغیر است، FK واقعی امکان‌پذیر نیست
    RequestTypeID            SMALLINT     NOT NULL REFERENCES wf.CartableRequestTypes(RequestTypeID),
    WorkflowID               INT          NULL REFERENCES wf.ApprovalWorkflows(WorkflowID),
    CurrentStepNo            SMALLINT     NOT NULL DEFAULT 1,   -- به wf.CartableItemSteps همین آیتم اشاره دارد، نه مستقیم به قالب wf.ApprovalWorkflowSteps
    CurrentApproverRoleID    INT          NULL REFERENCES sec.Roles(RoleID),   -- کپی از تعریف مرحله، برای کوئری سریع صف کارتابل
    CurrentApproverUserID    INT          NULL REFERENCES sec.Users(UserID),   -- ارجاع مستقیم/تفویض‌شده؛ یا SubmittedByUserID وقتی «عودت» شده
    StatusID                 SMALLINT     NOT NULL REFERENCES wf.CartableStatuses(StatusID),
    SubmittedByUserID        INT          NOT NULL REFERENCES sec.Users(UserID),
    SubmittedAt               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IX_CartableItems_Source ON wf.CartableItems(FormID, SourceRecordID);
-- صف «کارهای من»: جست‌وجوی سریع موارد PENDING به‌ازای نقش/کاربر جاری
CREATE INDEX IX_CartableItems_PendingByRole ON wf.CartableItems(CurrentApproverRoleID, StatusID) WHERE StatusID = 1;
CREATE INDEX IX_CartableItems_PendingByUser ON wf.CartableItems(CurrentApproverUserID, StatusID) WHERE StatusID = 1;

-- زنجیره‌ی نهاییِ محقق‌شده برای همین درخواست خاص: در لحظه‌ی ارسال، سرویس
-- پایتون شرط‌های wf.ApprovalStepConditions را در برابر اطلاعات همان سند
-- (مثلاً مبلغ کل) ارزیابی می‌کند و فقط مراحلِ منطبق (یا بدون‌شرط) را اینجا
-- ماده‌ی می‌کند و پیاپی شماره‌گذاری می‌کند. با این کار زنجیره‌ی واقعیِ طی‌شده
-- برای هر سند شفاف/قابل‌حسابرسی می‌ماند، حتی اگر بعداً تعریف قوانین در
-- wf.ApprovalWorkflowSteps تغییر کند.
CREATE TABLE wf.CartableItemSteps (
    CartableItemID BIGINT   NOT NULL REFERENCES wf.CartableItems(CartableItemID),
    StepNo         SMALLINT NOT NULL,
    ApproverRoleID INT      NOT NULL REFERENCES sec.Roles(RoleID),
    CONSTRAINT PK_CartableItemSteps PRIMARY KEY (CartableItemID, StepNo)
);

-- تاریخچه‌ی کامل اقدامات روی هر آیتم کارتابل (تایید/رد/عودت/ابطال/ارجاع/ارسال‌مجدد)
CREATE TABLE wf.CartableActions (
    ActionID        BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    CartableItemID  BIGINT       NOT NULL REFERENCES wf.CartableItems(CartableItemID),
    StepNo          SMALLINT     NOT NULL,
    ActionTypeID    SMALLINT     NOT NULL REFERENCES wf.CartableActionTypes(ActionTypeID),
    ActionByUserID  INT          NOT NULL REFERENCES sec.Users(UserID),
    Comment         TEXT         NULL,
    ActionAt        TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IX_CartableActions_Item ON wf.CartableActions(CartableItemID);
