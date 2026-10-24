-- R318: انتقال ماندهٔ تفصیلی با سند و ادغام کامل گردش دو تفصیلی (برگشت‌پذیر)، و تعریف دارایی ثابت در فرم تفصیلی.
-- هر سه پشت کلید روشن/خاموش‌اند و پیش‌فرض خاموش؛ با کلید خاموش رفتار برنامه همان قبلی است.

CREATE TABLE acc.detail_operations (
    operation_id              BIGSERIAL     PRIMARY KEY,
    company_id                INT           NOT NULL REFERENCES core.companies(company_id),
    operation_type            VARCHAR(20)   NOT NULL CHECK (operation_type IN ('TRANSFER', 'MERGE')),
    source_detail_account_id  INT           NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    target_detail_account_id  INT           NOT NULL REFERENCES acc.detail_accounts(detail_account_id),
    status_code               VARCHAR(20)   NOT NULL DEFAULT 'DONE' CHECK (status_code IN ('DONE', 'REVERSED')),
    journal_entry_id          INT           NULL REFERENCES acc.journal_entries(journal_entry_id),
    reversal_entry_id         INT           NULL REFERENCES acc.journal_entries(journal_entry_id),
    operation_date            DATE          NOT NULL,
    description               TEXT          NULL,
    source_was_active         BOOLEAN       NULL,
    summary                   JSONB         NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id        INT           NULL REFERENCES sec.users(user_id),
    created_at                TIMESTAMPTZ   NOT NULL DEFAULT now(),
    reversed_by_user_id       INT           NULL REFERENCES sec.users(user_id),
    reversed_at               TIMESTAMPTZ   NULL
);
CREATE INDEX ix_acc_detail_operations_source ON acc.detail_operations (company_id, source_detail_account_id);
CREATE INDEX ix_acc_detail_operations_target ON acc.detail_operations (company_id, target_detail_account_id);

-- هر ردیفی که در ادغام از مبدأ به مقصد رفت (برای برگشت دقیق)
CREATE TABLE acc.detail_merge_rows (
    merge_row_id  BIGSERIAL     PRIMARY KEY,
    operation_id  BIGINT        NOT NULL REFERENCES acc.detail_operations(operation_id) ON DELETE CASCADE,
    table_name    VARCHAR(130)  NOT NULL,
    column_name   VARCHAR(130)  NOT NULL,
    row_key       JSONB         NOT NULL
);
CREATE INDEX ix_acc_detail_merge_rows_operation ON acc.detail_merge_rows (operation_id);

INSERT INTO inv.feature_definitions (feature_code, name, category, requires_feature_code, description) VALUES
    ('GL_FA_IN_DETAIL_FORM', 'تعریف دارایی ثابت در فرم تعریف تفصیلی', 'ACCOUNTING', NULL,
     'مثل کالا: در فرم «تعریف تفصیلی» با انتخاب گروه «دارایی ثابت»، شناسنامهٔ کامل دارایی (طبقه، استهلاک، محل، مرکز هزینه، خرید و تولید) همان‌جا وارد و ذخیره می‌شود و حساب تفصیلی و دارایی با هم ساخته می‌شوند. عملیات مالی (سرمایه‌ای‌کردن، انتقال، استهلاک، فروش) همچنان از «دارایی‌ها» انجام می‌شود.'),
    ('GL_DETAIL_BALANCE_TRANSFER', 'انتقال ماندهٔ تفصیلی به تفصیلی دیگر با سند', 'ACCOUNTING', NULL,
     'ماندهٔ یک تفصیلی (به تفکیک حساب، ارز و تفصیلی‌های همراه) با یک سند حسابداری به تفصیلی دیگری از همان گروه منتقل می‌شود. سابقهٔ قبلی دست نمی‌خورد و با سند برگشتی قابل بازگشت است. دسترسی جدا: «تفصیلی: انتقال مانده با سند».'),
    ('GL_DETAIL_MERGE', 'ادغام کامل گردش دو تفصیلی', 'ACCOUNTING', NULL,
     'همهٔ گردش و سوابق یک تفصیلی (ردیف‌های سند، اسناد خرید و فروش، چک‌ها، آدرس‌ها و ...) به تفصیلی دیگر منتقل و تفصیلی قبلی غیرفعال می‌شود. هر ردیف جابه‌جاشده ثبت می‌شود تا ادغام کاملاً قابل برگشت باشد. برای کالا و دارایی ثابت مجاز نیست. دسترسی جدا: «تفصیلی: ادغام کامل گردش».')
ON CONFLICT (feature_code) DO NOTHING;
