-- R343: مدیریت اسناد (DMS) روی همان طرح doc (جدول قدیمی doc.attachments دست نمی‌خورد).
-- سند → نسخه‌ها → فایل‌ها؛ پیوند سند به رکوردهای ERP با نوع موجودیت و شناسه که پیش از ثبت در سرویس
-- (services/dms/entities.py) اعتبارسنجی می‌شود؛ درخواست عکس‌برداری موبایل با توکن یک‌بارمصرف که فقط
-- هش آن ذخیره می‌شود. همهٔ تغییرها افزایشی‌اند.

CREATE TABLE IF NOT EXISTS doc.dms_settings (
    company_id             INT          PRIMARY KEY REFERENCES core.companies(company_id),
    storage_mode           VARCHAR(4)   NOT NULL DEFAULT 'DB' CHECK (storage_mode IN ('DB', 'FS')),
    storage_root           VARCHAR(500) NULL,
    max_file_mb            INT          NOT NULL DEFAULT 25 CHECK (max_file_mb BETWEEN 1 AND 200),
    mobile_base_url        VARCHAR(300) NULL,
    capture_minutes        INT          NOT NULL DEFAULT 10 CHECK (capture_minutes BETWEEN 2 AND 120),
    capture_max_photos     INT          NOT NULL DEFAULT 10 CHECK (capture_max_photos BETWEEN 1 AND 30),
    expiry_reminder_days   INT          NOT NULL DEFAULT 30 CHECK (expiry_reminder_days BETWEEN 0 AND 365),
    keep_gps               BOOLEAN      NOT NULL DEFAULT FALSE,
    text_extraction        BOOLEAN      NOT NULL DEFAULT TRUE,
    image_ocr              BOOLEAN      NOT NULL DEFAULT FALSE,
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS doc.categories (
    category_id         INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id          INT          NOT NULL REFERENCES core.companies(company_id),
    parent_category_id  INT          NULL REFERENCES doc.categories(category_id),
    name                VARCHAR(150) NOT NULL,
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_categories_name
    ON doc.categories(company_id, COALESCE(parent_category_id, 0), name);

CREATE TABLE IF NOT EXISTS doc.tags (
    tag_id      INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id  INT          NOT NULL REFERENCES core.companies(company_id),
    name        VARCHAR(80)  NOT NULL,
    UNIQUE (company_id, name)
);

-- محتوای فایل: در حالت DB خود بایت‌ها، در حالت FS کلید نسبی زیر پوشهٔ ذخیره‌سازی
CREATE TABLE IF NOT EXISTS doc.files (
    file_id         BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id      INT           NOT NULL REFERENCES core.companies(company_id),
    storage_mode    VARCHAR(4)    NOT NULL CHECK (storage_mode IN ('DB', 'FS')),
    storage_key     VARCHAR(300)  NULL,
    content         BYTEA         NULL,
    thumbnail       BYTEA         NULL,
    sha256          BYTEA         NOT NULL,
    size_bytes      BIGINT        NOT NULL,
    mime_type       VARCHAR(100)  NOT NULL,
    extension       VARCHAR(10)   NOT NULL,
    original_name   VARCHAR(260)  NOT NULL,
    width           INT           NULL,
    height          INT           NULL,
    text_status     VARCHAR(8)    NOT NULL DEFAULT 'NONE'
                    CHECK (text_status IN ('NONE', 'PENDING', 'DONE', 'EMPTY', 'SKIPPED', 'FAILED')),
    text_content    TEXT          NULL,
    created_by_user_id INT        NOT NULL REFERENCES sec.users(user_id),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CHECK ((storage_mode = 'DB' AND content IS NOT NULL) OR (storage_mode = 'FS' AND storage_key IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_doc_files_text_pending ON doc.files(company_id) WHERE text_status = 'PENDING';

CREATE TABLE IF NOT EXISTS doc.documents (
    document_id            BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id             INT           NOT NULL REFERENCES core.companies(company_id),
    branch_id              INT           NULL REFERENCES comm.branches(branch_id),
    document_no            VARCHAR(30)   NOT NULL,
    title                  VARCHAR(300)  NOT NULL,
    document_type_code     VARCHAR(20)   NOT NULL,
    category_id            INT           NULL REFERENCES doc.categories(category_id),
    confidentiality_code   VARCHAR(12)   NOT NULL DEFAULT 'INTERNAL'
                           CHECK (confidentiality_code IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'SECRET')),
    status_code            VARCHAR(14)   NOT NULL DEFAULT 'DRAFT'
                           CHECK (status_code IN ('DRAFT', 'PENDING', 'IN_REVIEW', 'NEEDS_CHANGES', 'REJECTED',
                                                  'APPROVED', 'OBSOLETE', 'ARCHIVED')),
    owner_user_id          INT           NOT NULL REFERENCES sec.users(user_id),
    responsible_user_id    INT           NULL REFERENCES sec.users(user_id),
    issue_date             DATE          NULL,
    valid_from             DATE          NULL,
    expiry_date            DATE          NULL,
    description            TEXT          NULL,
    current_version_id     BIGINT        NULL,
    approved_version_id    BIGINT        NULL,
    archived_from_status   VARCHAR(14)   NULL,
    is_deleted             BOOLEAN       NOT NULL DEFAULT FALSE,
    deleted_by_user_id     INT           NULL REFERENCES sec.users(user_id),
    deleted_at             TIMESTAMPTZ   NULL,
    created_by_user_id     INT           NOT NULL REFERENCES sec.users(user_id),
    created_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_by_user_id     INT           NULL REFERENCES sec.users(user_id),
    updated_at             TIMESTAMPTZ   NOT NULL DEFAULT now(),
    row_version            INT           NOT NULL DEFAULT 1,
    UNIQUE (company_id, document_no),
    CHECK (expiry_date IS NULL OR valid_from IS NULL OR expiry_date >= valid_from)
);
CREATE INDEX IF NOT EXISTS ix_doc_documents_company_status ON doc.documents(company_id, status_code) WHERE NOT is_deleted;
CREATE INDEX IF NOT EXISTS ix_doc_documents_expiry ON doc.documents(company_id, expiry_date) WHERE NOT is_deleted AND expiry_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_doc_documents_title ON doc.documents(company_id, lower(title));

CREATE TABLE IF NOT EXISTS doc.document_versions (
    version_id          BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id         BIGINT        NOT NULL REFERENCES doc.documents(document_id),
    version_no          INT           NOT NULL,
    change_reason       VARCHAR(500)  NULL,
    source_code         VARCHAR(10)   NOT NULL DEFAULT 'DESKTOP' CHECK (source_code IN ('DESKTOP', 'MOBILE', 'WEB', 'API')),
    created_by_user_id  INT           NOT NULL REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (document_id, version_no)
);

CREATE TABLE IF NOT EXISTS doc.version_files (
    version_id  BIGINT    NOT NULL REFERENCES doc.document_versions(version_id),
    position    SMALLINT  NOT NULL,
    file_id     BIGINT    NOT NULL REFERENCES doc.files(file_id),
    PRIMARY KEY (version_id, position)
);
CREATE INDEX IF NOT EXISTS ix_doc_version_files_file ON doc.version_files(file_id);

ALTER TABLE doc.documents DROP CONSTRAINT IF EXISTS fk_doc_documents_current_version;
ALTER TABLE doc.documents ADD CONSTRAINT fk_doc_documents_current_version
    FOREIGN KEY (current_version_id) REFERENCES doc.document_versions(version_id);
ALTER TABLE doc.documents DROP CONSTRAINT IF EXISTS fk_doc_documents_approved_version;
ALTER TABLE doc.documents ADD CONSTRAINT fk_doc_documents_approved_version
    FOREIGN KEY (approved_version_id) REFERENCES doc.document_versions(version_id);

CREATE TABLE IF NOT EXISTS doc.document_tags (
    document_id  BIGINT  NOT NULL REFERENCES doc.documents(document_id),
    tag_id       INT     NOT NULL REFERENCES doc.tags(tag_id),
    PRIMARY KEY (document_id, tag_id)
);

-- پیوند به رکورد ERP: نوع موجودیت از فهرست ثابت سرویس، وجود و شرکت رکورد پیش از ثبت بررسی می‌شود
CREATE TABLE IF NOT EXISTS doc.document_links (
    link_id             BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id         BIGINT       NOT NULL REFERENCES doc.documents(document_id),
    company_id          INT          NOT NULL REFERENCES core.companies(company_id),
    entity_type         VARCHAR(40)  NOT NULL,
    entity_id           BIGINT       NOT NULL,
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_by_user_id  INT          NOT NULL REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    removed_by_user_id  INT          NULL REFERENCES sec.users(user_id),
    removed_at          TIMESTAMPTZ  NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_links_active ON doc.document_links(document_id, entity_type, entity_id) WHERE is_active;
CREATE INDEX IF NOT EXISTS ix_doc_links_entity ON doc.document_links(company_id, entity_type, entity_id) WHERE is_active;

-- رد رویدادها: تاریخچهٔ گردش کار، نسخه، پیوند، دانلود و عکس‌برداری (بدون توکن و محتوای فایل)
CREATE TABLE IF NOT EXISTS doc.document_events (
    event_id      BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id    INT           NOT NULL REFERENCES core.companies(company_id),
    document_id   BIGINT        NULL REFERENCES doc.documents(document_id),
    event_code    VARCHAR(30)   NOT NULL,
    from_status   VARCHAR(14)   NULL,
    to_status     VARCHAR(14)   NULL,
    version_id    BIGINT        NULL REFERENCES doc.document_versions(version_id),
    user_id       INT           NULL REFERENCES sec.users(user_id),
    note          VARCHAR(1000) NULL,
    details       JSONB         NULL,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_doc_events_document ON doc.document_events(document_id, event_id);

CREATE TABLE IF NOT EXISTS doc.document_reminders (
    reminder_id       BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id       BIGINT       NOT NULL REFERENCES doc.documents(document_id),
    reminder_kind     VARCHAR(14)  NOT NULL CHECK (reminder_kind IN ('BEFORE_EXPIRY', 'EXPIRED')),
    expiry_date       DATE         NOT NULL,
    notified_user_ids INT[]        NOT NULL DEFAULT '{}',
    result_code       VARCHAR(10)  NOT NULL DEFAULT 'SENT',
    sent_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (document_id, reminder_kind, expiry_date)
);

CREATE TABLE IF NOT EXISTS doc.capture_requests (
    request_id            BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id            INT           NOT NULL REFERENCES core.companies(company_id),
    branch_id             INT           NULL REFERENCES comm.branches(branch_id),
    token_hash            BYTEA         NOT NULL UNIQUE,
    requested_by_user_id  INT           NOT NULL REFERENCES sec.users(user_id),
    target_entity_type    VARCHAR(40)   NULL,
    target_entity_id      BIGINT        NULL,
    target_document_id    BIGINT        NULL REFERENCES doc.documents(document_id),
    document_type_code    VARCHAR(20)   NOT NULL DEFAULT 'IMAGE',
    category_id           INT           NULL REFERENCES doc.categories(category_id),
    title                 VARCHAR(300)  NULL,
    max_photos            INT           NOT NULL DEFAULT 10,
    status_code           VARCHAR(10)   NOT NULL DEFAULT 'PENDING'
                          CHECK (status_code IN ('PENDING', 'OPENED', 'CAPTURING', 'UPLOADING', 'COMPLETED',
                                                 'CANCELLED', 'EXPIRED', 'FAILED')),
    attempt_count         INT           NOT NULL DEFAULT 0,
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    expires_at            TIMESTAMPTZ   NOT NULL,
    opened_at             TIMESTAMPTZ   NULL,
    consumed_at           TIMESTAMPTZ   NULL,
    completed_at          TIMESTAMPTZ   NULL,
    cancelled_at          TIMESTAMPTZ   NULL,
    cancelled_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    result_document_id    BIGINT        NULL REFERENCES doc.documents(document_id),
    result_version_id     BIGINT        NULL REFERENCES doc.document_versions(version_id),
    upload_key            VARCHAR(80)   NULL,
    failure_reason        VARCHAR(300)  NULL,
    CHECK (target_document_id IS NOT NULL OR (target_entity_type IS NOT NULL AND target_entity_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_doc_capture_active ON doc.capture_requests(company_id, requested_by_user_id, status_code);
