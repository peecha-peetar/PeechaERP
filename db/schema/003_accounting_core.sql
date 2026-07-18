-- پیچا | ماژول حسابداری (دفتر کل): سال/دوره‌ی مالی، کدینگ حسابداری درختی،
-- تفصیلی شناور چندبعدی، اسناد حسابداری و آرتیکل‌ها
-- PostgreSQL 13+
-- پیش‌نیاز: 001_core_i18n_and_tenancy.sql، 002_security_rbac.sql (برای sec.Users)

CREATE SCHEMA acc;

-- ---------------------------------------------------------------------
-- سال مالی و دوره‌های مالی (برای قفل‌کردن دوره‌های بسته‌شده)
-- ---------------------------------------------------------------------
CREATE TABLE acc.FiscalYears (
    FiscalYearID INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    CompanyID    INT          NOT NULL REFERENCES core.Companies(CompanyID),
    Code         VARCHAR(20)  NOT NULL,   -- مثلاً "1404"
    StartDate    DATE         NOT NULL,
    EndDate      DATE         NOT NULL,
    IsClosed     BOOLEAN      NOT NULL DEFAULT FALSE,
    CONSTRAINT UQ_FiscalYears UNIQUE (CompanyID, Code),
    CONSTRAINT CK_FiscalYears_Dates CHECK (EndDate > StartDate)
);

CREATE TABLE acc.FiscalPeriods (
    FiscalPeriodID INT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    FiscalYearID   INT      NOT NULL REFERENCES acc.FiscalYears(FiscalYearID),
    PeriodNo       SMALLINT NOT NULL,   -- 1..12 (یا بیشتر در صورت نیاز)
    StartDate      DATE     NOT NULL,
    EndDate        DATE     NOT NULL,
    IsClosed       BOOLEAN  NOT NULL DEFAULT FALSE,
    CONSTRAINT UQ_FiscalPeriods UNIQUE (FiscalYearID, PeriodNo),
    CONSTRAINT CK_FiscalPeriods_Dates CHECK (EndDate > StartDate)
);

-- ---------------------------------------------------------------------
-- کدینگ حسابداری (سرفصل حساب‌ها) — ۴ سطح: گروه(۱) / کل(۲) / معین(۳) به‌صورت
-- درخت والد-فرزند، و تفصیلی شناور(۴) که چون چندبعدی و هم‌زمان‌پذیر است
-- (یک معین می‌تواند هم‌زمان چند بعد تفصیلی بخواهد) عمداً به‌صورت یک سیستم
-- جدا (چند جدول پایین‌تر) مدل شده، نه یک والد/فرزند دیگر در همین درخت.
-- ---------------------------------------------------------------------
CREATE TABLE acc.AccountNatures (            -- ماهیت حساب: بدهکار/بستانکار/دوطرفه
    NatureID SMALLINT    NOT NULL PRIMARY KEY,
    Code     VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO acc.AccountNatures (NatureID, Code) VALUES
    (1, 'DEBIT'), (2, 'CREDIT'), (3, 'BOTH');

CREATE TABLE acc.AccountCategories (         -- برای طبقه‌بندی در صورت‌های مالی
    CategoryID SMALLINT   NOT NULL PRIMARY KEY,
    Code       VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO acc.AccountCategories (CategoryID, Code) VALUES
    (1, 'ASSET'), (2, 'LIABILITY'), (3, 'EQUITY'), (4, 'REVENUE'), (5, 'EXPENSE');

-- نوع حساب: ترازنامه‌ای (دائمی، در پایان سال مالی بسته نمی‌شود) در برابر
-- موقت (نظیر درآمد/هزینه؛ با سند اختتامیه به صفر می‌رسد). معمولاً در سطح
-- گروه تعیین می‌شود و کل/معین زیرمجموعه‌اش همان مقدار را به ارث می‌برند
-- (این هم‌خوانی در لایه‌ی سرویس بررسی می‌شود، نه با CHECK بین‌ردیفی).
CREATE TABLE acc.AccountTypes (
    AccountTypeID SMALLINT    NOT NULL PRIMARY KEY,
    Code          VARCHAR(20) NOT NULL UNIQUE     -- PERMANENT (ترازنامه‌ای), TEMPORARY (موقت)
);
INSERT INTO acc.AccountTypes (AccountTypeID, Code) VALUES
    (1, 'PERMANENT'), (2, 'TEMPORARY');

CREATE TABLE acc.ChartOfAccounts (
    AccountID        INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    CompanyID        INT          NOT NULL REFERENCES core.Companies(CompanyID),
    ParentAccountID  INT          NULL REFERENCES acc.ChartOfAccounts(AccountID),
    SegmentCode      VARCHAR(20)  NOT NULL,   -- کد این گره به‌تنهایی، مثلاً "01"
    FullCode         VARCHAR(100) NOT NULL,   -- کد کامل ترکیبی برای نمایش/مرتب‌سازی سریع، مثلاً "11.01"
    AccountLevel     SMALLINT     NOT NULL,   -- ۱=گروه، ۲=کل، ۳=معین (صرفاً برچسب گزارشی روی همین درخت)
    NatureID         SMALLINT     NOT NULL REFERENCES acc.AccountNatures(NatureID),
    CategoryID       SMALLINT     NOT NULL REFERENCES acc.AccountCategories(CategoryID),
    AccountTypeID    SMALLINT     NOT NULL REFERENCES acc.AccountTypes(AccountTypeID),
    IsPostable       BOOLEAN      NOT NULL DEFAULT FALSE, -- فقط حساب‌های Postable می‌توانند طرف سند قرار بگیرند
    CurrencyID       INT          NULL REFERENCES core.Currencies(CurrencyID), -- NULL = هر ارز فعال شرکت؛ مقداردار = این حساب فقط با این ارز
    IsActive         BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT UQ_ChartOfAccounts_FullCode UNIQUE (CompanyID, FullCode)
);
CREATE INDEX IX_ChartOfAccounts_Parent ON acc.ChartOfAccounts(ParentAccountID);

-- حساب‌های واسطی که موتور «سند اختتامیه‌ی خودکار» به آن‌ها نیاز دارد:
-- بستن حساب‌های موقت به حساب واسط سود/زیان، سپس انتقال آن به سود انباشته.
CREATE TABLE acc.CompanyAccountingSettings (
    CompanyID                 INT NOT NULL PRIMARY KEY REFERENCES core.Companies(CompanyID),
    ProfitAndLossAccountID    INT NULL REFERENCES acc.ChartOfAccounts(AccountID),
    RetainedEarningsAccountID INT NULL REFERENCES acc.ChartOfAccounts(AccountID)
);

-- ---------------------------------------------------------------------
-- تفصیلی شناور چندبعدی: هر معین می‌تواند صفر یا چند بعد تفصیلی بپذیرد
-- (مثلاً حساب «بدهکاران تجاری» هم بعد «مشتری» و هم بعد «مرکز هزینه» بخواهد)
-- ---------------------------------------------------------------------
CREATE TABLE acc.DetailDimensionTypes (      -- انواع بعد تفصیلی
    DimensionTypeID SMALLINT    GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    CompanyID       INT         NOT NULL REFERENCES core.Companies(CompanyID),
    Code            VARCHAR(30) NOT NULL,    -- CUSTOMER, VENDOR, COST_CENTER, PROJECT, EMPLOYEE, CASHBANK ...
    IsActive        BOOLEAN     NOT NULL DEFAULT TRUE,
    CONSTRAINT UQ_DetailDimensionTypes UNIQUE (CompanyID, Code)
);

CREATE TABLE acc.DetailAccounts (            -- نمونه‌های واقعی هر بعد (مثلاً یک مشتری خاص)
    DetailAccountID INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    CompanyID       INT          NOT NULL REFERENCES core.Companies(CompanyID),
    DimensionTypeID SMALLINT     NOT NULL REFERENCES acc.DetailDimensionTypes(DimensionTypeID),
    Code            VARCHAR(30)  NOT NULL,
    IsActive        BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT UQ_DetailAccounts UNIQUE (CompanyID, DimensionTypeID, Code)
);

CREATE TABLE acc.AccountDetailDimensions (   -- کدام معین‌ها کدام ابعاد را می‌پذیرند/الزامی است
    AccountID       INT      NOT NULL REFERENCES acc.ChartOfAccounts(AccountID),
    DimensionTypeID SMALLINT NOT NULL REFERENCES acc.DetailDimensionTypes(DimensionTypeID),
    IsRequired      BOOLEAN  NOT NULL DEFAULT TRUE,
    CONSTRAINT PK_AccountDetailDimensions PRIMARY KEY (AccountID, DimensionTypeID)
);

-- ---------------------------------------------------------------------
-- اسناد حسابداری
-- ---------------------------------------------------------------------
CREATE TABLE acc.JournalEntryTypes (
    EntryTypeID SMALLINT    NOT NULL PRIMARY KEY,
    Code        VARCHAR(20) NOT NULL UNIQUE   -- NORMAL, OPENING, CLOSING, ADJUSTING
);
INSERT INTO acc.JournalEntryTypes (EntryTypeID, Code) VALUES
    (1, 'NORMAL'), (2, 'OPENING'), (3, 'CLOSING'), (4, 'ADJUSTING');

CREATE TABLE acc.JournalEntryStatuses (
    StatusID SMALLINT   NOT NULL PRIMARY KEY,
    Code     VARCHAR(20) NOT NULL UNIQUE
);
INSERT INTO acc.JournalEntryStatuses (StatusID, Code) VALUES
    (1, 'TEMPORARY'),   -- موقت: قابل ویرایش/ادغام، شماره‌اش هم قابل تغییر است
    (2, 'PERMANENT'),   -- دائم: پس از تایید در کارتابل؛ شماره‌ی ثابت گرفته و دیگر قابل ویرایش نیست
    (3, 'REVERSED'),    -- برگشت‌خورده: یک سند برگشتی جدید آن را خنثی کرده
    (4, 'CANCELLED');   -- ابطال‌شده/ادغام‌شده در سند موقت دیگر

-- هر سند هم شماره‌ی موقت دارد (از لحظه‌ی ایجاد، قابل تغییر/ادغام) و هم
-- شماره‌ی ثابت (فقط پس از تایید نهایی در کارتابل تخصیص می‌یابد؛ پیوسته و
-- پس از تخصیص غیرقابل تغییر — enforce شده با تریگر پایین همین فایل).
CREATE TABLE acc.JournalEntries (            -- هدر سند
    JournalEntryID    INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    CompanyID         INT          NOT NULL REFERENCES core.Companies(CompanyID),
    FiscalYearID      INT          NOT NULL REFERENCES acc.FiscalYears(FiscalYearID),
    TemporaryNo       INT          NOT NULL,   -- شماره موقت؛ تخصیص/تغییر/ادغام آن بر عهده‌ی لایه‌ی سرویس است
    PermanentNo       INT          NULL,       -- شماره ثابت؛ فقط هنگام تبدیل به PERMANENT پر می‌شود
    DocumentDate      DATE         NOT NULL,
    EntryTypeID       SMALLINT     NOT NULL REFERENCES acc.JournalEntryTypes(EntryTypeID),
    StatusID          SMALLINT     NOT NULL REFERENCES acc.JournalEntryStatuses(StatusID),
    Description       TEXT         NULL,
    IsSystemGenerated BOOLEAN      NOT NULL DEFAULT FALSE, -- مثلاً سند اختتامیه‌ی خودکار
    ReversedEntryID   INT          NULL REFERENCES acc.JournalEntries(JournalEntryID), -- اگر این سند، برگشتِ سند دیگری است
    CreatedByUserID   INT          NOT NULL REFERENCES sec.Users(UserID),
    CreatedAt         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PostedByUserID    INT          NULL REFERENCES sec.Users(UserID),   -- کاربری که در کارتابل تاییدِ نهایی را زده
    PostedAt          TIMESTAMPTZ  NULL,
    CONSTRAINT UQ_JournalEntries_TemporaryNo UNIQUE (CompanyID, FiscalYearID, TemporaryNo)
);
-- شماره‌ی ثابت فقط وقتی مقدار دارد یکتاست (بین چند سند TEMPORARY هنوز NULL است)
CREATE UNIQUE INDEX UX_JournalEntries_PermanentNo
    ON acc.JournalEntries(CompanyID, FiscalYearID, PermanentNo)
    WHERE PermanentNo IS NOT NULL;

CREATE FUNCTION acc.prevent_permanentno_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.PermanentNo IS NOT NULL AND (NEW.PermanentNo IS NULL OR NEW.PermanentNo <> OLD.PermanentNo) THEN
        RAISE EXCEPTION 'شماره ثابت سند حسابداری پس از تخصیص غیرقابل تغییر است.';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER TR_JournalEntries_PreventPermanentNoChange
    BEFORE UPDATE ON acc.JournalEntries
    FOR EACH ROW EXECUTE FUNCTION acc.prevent_permanentno_change();

CREATE TABLE acc.JournalEntryLines (         -- آرتیکل‌های سند (ردیف‌های بدهکار/بستانکار)
    LineID           BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    JournalEntryID   INT           NOT NULL REFERENCES acc.JournalEntries(JournalEntryID),
    LineNo           SMALLINT      NOT NULL,
    AccountID        INT           NOT NULL REFERENCES acc.ChartOfAccounts(AccountID),
    Description      TEXT          NULL,
    CurrencyID       INT           NOT NULL REFERENCES core.Currencies(CurrencyID),
    ExchangeRate     NUMERIC(18,6) NOT NULL DEFAULT 1,
    DebitAmountFC    NUMERIC(18,2) NOT NULL DEFAULT 0,  -- مبلغ به ارز ردیف
    CreditAmountFC   NUMERIC(18,2) NOT NULL DEFAULT 0,
    DebitAmountBase  NUMERIC(18,2) GENERATED ALWAYS AS (ROUND(DebitAmountFC  * ExchangeRate, 2)) STORED, -- معادل ارز پایه‌ی شرکت
    CreditAmountBase NUMERIC(18,2) GENERATED ALWAYS AS (ROUND(CreditAmountFC * ExchangeRate, 2)) STORED,
    CONSTRAINT UQ_JournalEntryLines UNIQUE (JournalEntryID, LineNo),
    CONSTRAINT CK_JournalEntryLines_OneSided CHECK (
        (DebitAmountFC > 0 AND CreditAmountFC = 0) OR
        (CreditAmountFC > 0 AND DebitAmountFC = 0)
    )
);
CREATE INDEX IX_JournalEntryLines_Account ON acc.JournalEntryLines(AccountID);

CREATE TABLE acc.JournalEntryLineDetails (   -- تخصیص تفصیلی‌های هر ردیف سند
    LineID          BIGINT   NOT NULL REFERENCES acc.JournalEntryLines(LineID),
    DimensionTypeID SMALLINT NOT NULL REFERENCES acc.DetailDimensionTypes(DimensionTypeID),
    DetailAccountID INT      NOT NULL REFERENCES acc.DetailAccounts(DetailAccountID),
    CONSTRAINT PK_JournalEntryLineDetails PRIMARY KEY (LineID, DimensionTypeID)
);
