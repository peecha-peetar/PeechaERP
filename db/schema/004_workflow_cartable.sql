-- پیچا | کارتابل: صف تایید سراسری برای اسناد همه‌ی ماژول‌ها (حسابداری، انبار،
-- خرید و فروش، خزانه‌داری، ...)؛ هر سند از هر ماژول با ارجاع به sec.Forms
-- (کاتالوگ فرم‌های موجود) و یک شناسه‌ی رکورد مبدا در این صف قرار می‌گیرد.
-- سازگار با SQL Server 2016
-- پیش‌نیاز: 002_security_rbac.sql

CREATE SCHEMA wf;
GO

CREATE TABLE wf.CartableStatuses (
    StatusID TINYINT     NOT NULL PRIMARY KEY,
    Code     VARCHAR(20) NOT NULL UNIQUE
);
GO
INSERT INTO wf.CartableStatuses (StatusID, Code) VALUES
    (1, 'PENDING'), (2, 'APPROVED'), (3, 'REJECTED'), (4, 'RETURNED'), (5, 'CANCELLED');
GO

CREATE TABLE wf.CartableActionTypes (
    ActionTypeID TINYINT     NOT NULL PRIMARY KEY,
    Code         VARCHAR(20) NOT NULL UNIQUE
);
GO
INSERT INTO wf.CartableActionTypes (ActionTypeID, Code) VALUES
    (1, 'APPROVE'), (2, 'REJECT'), (3, 'RETURN'), (4, 'CANCEL'), (5, 'DELEGATE');
GO

-- تعریف زنجیره‌ی تایید برای یک نوع سند مشخص در یک شرکت (اختیاری؛ نبودِ
-- تعریف یعنی تک‌مرحله‌ای با تاییدکننده‌ای که لایه‌ی سرویس مشخص می‌کند)
CREATE TABLE wf.ApprovalWorkflows (
    WorkflowID INT         NOT NULL IDENTITY(1,1) PRIMARY KEY,
    CompanyID  INT         NOT NULL REFERENCES core.Companies(CompanyID),
    FormID     INT         NOT NULL REFERENCES sec.Forms(FormID),
    Code       VARCHAR(50) NOT NULL,
    IsActive   BIT         NOT NULL CONSTRAINT DF_ApprovalWorkflows_IsActive DEFAULT (1),
    CONSTRAINT UQ_ApprovalWorkflows UNIQUE (CompanyID, FormID, Code)
);
GO

CREATE TABLE wf.ApprovalWorkflowSteps (
    WorkflowID     INT      NOT NULL REFERENCES wf.ApprovalWorkflows(WorkflowID),
    StepNo         SMALLINT NOT NULL,
    ApproverRoleID INT      NOT NULL REFERENCES sec.Roles(RoleID),   -- هر کاربرِ دارای این نقش می‌تواند این مرحله را تایید کند
    CONSTRAINT PK_ApprovalWorkflowSteps PRIMARY KEY (WorkflowID, StepNo)
);
GO

-- وضعیت زنده‌ی هر سند در کارتابل (یک سند در هر لحظه حداکثر یک ردیف PENDING دارد)
CREATE TABLE wf.CartableItems (
    CartableItemID        BIGINT       NOT NULL IDENTITY(1,1) PRIMARY KEY,
    CompanyID              INT          NOT NULL REFERENCES core.Companies(CompanyID),
    FormID                  INT          NOT NULL REFERENCES sec.Forms(FormID),   -- نوع سند (مثلاً «سند حسابداری»، «حواله انبار»، ...)
    SourceRecordID          BIGINT       NOT NULL,   -- کلید رکورد واقعی در جدول همان ماژول (مثلاً acc.JournalEntries.JournalEntryID)؛ چون نوع منبع متغیر است، FK واقعی امکان‌پذیر نیست
    WorkflowID              INT          NULL REFERENCES wf.ApprovalWorkflows(WorkflowID),
    CurrentStepNo           SMALLINT     NOT NULL CONSTRAINT DF_CartableItems_StepNo DEFAULT (1),
    CurrentApproverRoleID   INT          NULL REFERENCES sec.Roles(RoleID),   -- کپی از تعریف مرحله، برای کوئری سریع صف کارتابل
    CurrentApproverUserID   INT          NULL REFERENCES sec.Users(UserID),   -- ارجاع مستقیم/تفویض‌شده به یک کاربر خاص
    StatusID                TINYINT      NOT NULL REFERENCES wf.CartableStatuses(StatusID),
    SubmittedByUserID       INT          NOT NULL REFERENCES sec.Users(UserID),
    SubmittedAt             DATETIME2(0) NOT NULL CONSTRAINT DF_CartableItems_SubmittedAt DEFAULT (SYSUTCDATETIME())
);
GO
CREATE INDEX IX_CartableItems_Source ON wf.CartableItems(FormID, SourceRecordID);
GO
-- صف «کارهای من»: جست‌وجوی سریع موارد PENDING به‌ازای نقش/کاربر جاری
CREATE INDEX IX_CartableItems_PendingByRole ON wf.CartableItems(CurrentApproverRoleID, StatusID) WHERE StatusID = 1;
CREATE INDEX IX_CartableItems_PendingByUser ON wf.CartableItems(CurrentApproverUserID, StatusID) WHERE StatusID = 1;
GO

-- تاریخچه‌ی کامل اقدامات روی هر آیتم کارتابل (تایید/رد/عودت/ابطال/ارجاع)
CREATE TABLE wf.CartableActions (
    ActionID        BIGINT       NOT NULL IDENTITY(1,1) PRIMARY KEY,
    CartableItemID  BIGINT       NOT NULL REFERENCES wf.CartableItems(CartableItemID),
    StepNo          SMALLINT     NOT NULL,
    ActionTypeID    TINYINT      NOT NULL REFERENCES wf.CartableActionTypes(ActionTypeID),
    ActionByUserID  INT          NOT NULL REFERENCES sec.Users(UserID),
    Comment         NVARCHAR(500) NULL,
    ActionAt        DATETIME2(0) NOT NULL CONSTRAINT DF_CartableActions_ActionAt DEFAULT (SYSUTCDATETIME())
);
GO
CREATE INDEX IX_CartableActions_Item ON wf.CartableActions(CartableItemID);
GO
