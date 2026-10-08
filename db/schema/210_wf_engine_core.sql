-- پیچا R291 — موتور گردش کار و اتوماسیون (فاز ۱: هسته). افزایشی روی اسکیمای موجود wf؛ جدول‌های کارتابل قدیمی دست نمی‌خورند.
-- تعریفِ داده‌محور و نسخه‌دار، رویدادِ ماندگار (Outbox)، اجرای ماندگار، دفترِ اجرای یکتا (Idempotency)، استثنا و زمان‌سنج.
-- برگشت: db/rollback/210_wf_engine_core_down.sql

CREATE TABLE IF NOT EXISTS wf.definitions (
    definition_id       SERIAL        PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    code                VARCHAR(50)   NOT NULL,
    name                VARCHAR(200)  NOT NULL,
    description         VARCHAR(1000) NULL,
    module_code         VARCHAR(20)   NULL,
    entity_type         VARCHAR(50)   NULL,
    category            VARCHAR(30)   NULL,
    template_code       VARCHAR(60)   NULL,
    status_code         VARCHAR(12)   NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'TESTING', 'PUBLISHED', 'ACTIVE', 'PAUSED', 'ARCHIVED')),
    active_version_id   INT           NULL,
    created_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS wf.definition_versions (
    version_id            SERIAL        PRIMARY KEY,
    definition_id         INT           NOT NULL REFERENCES wf.definitions(definition_id) ON DELETE CASCADE,
    version_no            INT           NOT NULL,
    graph                 JSONB         NOT NULL DEFAULT '{}'::jsonb,
    checksum              VARCHAR(64)   NULL,
    status_code           VARCHAR(12)   NOT NULL DEFAULT 'DRAFT'
        CHECK (status_code IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED')),
    notes                 VARCHAR(500)  NULL,
    created_by_user_id    INT           NULL REFERENCES sec.users(user_id),
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    published_by_user_id  INT           NULL REFERENCES sec.users(user_id),
    published_at          TIMESTAMPTZ   NULL,
    UNIQUE (definition_id, version_no)
);

ALTER TABLE wf.definitions DROP CONSTRAINT IF EXISTS fk_wf_definitions_active_version;
ALTER TABLE wf.definitions ADD CONSTRAINT fk_wf_definitions_active_version
    FOREIGN KEY (active_version_id) REFERENCES wf.definition_versions(version_id);

-- جستجوی سریعِ «کدام تعریف به این رویداد گوش می‌دهد» -- فقط نسخهٔ فعالِ هر تعریف
CREATE TABLE IF NOT EXISTS wf.definition_triggers (
    trigger_id      SERIAL       PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES core.companies(company_id),
    definition_id   INT          NOT NULL REFERENCES wf.definitions(definition_id) ON DELETE CASCADE,
    version_id      INT          NOT NULL REFERENCES wf.definition_versions(version_id) ON DELETE CASCADE,
    trigger_type    VARCHAR(12)  NOT NULL CHECK (trigger_type IN ('EVENT', 'SCHEDULE', 'SCAN', 'MANUAL')),
    event_type      VARCHAR(80)  NULL,
    entity_type     VARCHAR(50)  NULL,
    config          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_wf_triggers_event ON wf.definition_triggers (company_id, event_type) WHERE is_active;

-- Outbox: رویداد در همان تراکنشِ عملیاتِ اصلی ثبت می‌شود و پس از commit پردازش می‌شود (بعد از ری‌استارت هم)
CREATE TABLE IF NOT EXISTS wf.events (
    event_id               BIGSERIAL     PRIMARY KEY,
    company_id             INT           NOT NULL REFERENCES core.companies(company_id),
    event_type             VARCHAR(80)   NOT NULL,
    entity_type            VARCHAR(50)   NULL,
    entity_id              BIGINT        NULL,
    payload                JSONB         NOT NULL DEFAULT '{}'::jsonb,
    dedupe_key             VARCHAR(200)  NULL,
    actor_user_id          INT           NULL REFERENCES sec.users(user_id),
    causation_instance_id  BIGINT        NULL,
    depth                  SMALLINT      NOT NULL DEFAULT 0,
    status_code            VARCHAR(10)   NOT NULL DEFAULT 'PENDING'
        CHECK (status_code IN ('PENDING', 'DONE', 'FAILED', 'SKIPPED')),
    attempts               SMALLINT      NOT NULL DEFAULT 0,
    last_error             TEXT          NULL,
    locked_until           TIMESTAMPTZ   NULL,
    occurred_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    processed_at           TIMESTAMPTZ   NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_wf_events_dedupe ON wf.events (company_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_wf_events_pending ON wf.events (occurred_at) WHERE status_code = 'PENDING';
CREATE INDEX IF NOT EXISTS ix_wf_events_entity ON wf.events (company_id, entity_type, entity_id);

CREATE TABLE IF NOT EXISTS wf.instances (
    instance_id          BIGSERIAL     PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    definition_id        INT           NOT NULL REFERENCES wf.definitions(definition_id),
    version_id           INT           NOT NULL REFERENCES wf.definition_versions(version_id),
    entity_type          VARCHAR(50)   NULL,
    entity_id            BIGINT        NULL,
    title                VARCHAR(300)  NULL,
    status_code          VARCHAR(12)   NOT NULL DEFAULT 'RUNNING'
        CHECK (status_code IN ('RUNNING', 'WAITING', 'COMPLETED', 'FAILED', 'CANCELLED', 'SUSPENDED')),
    outcome_code         VARCHAR(20)   NULL,
    tokens               JSONB         NOT NULL DEFAULT '[]'::jsonb,
    context              JSONB         NOT NULL DEFAULT '{}'::jsonb,
    variables            JSONB         NOT NULL DEFAULT '{}'::jsonb,
    correlation_key      VARCHAR(200)  NULL,
    trigger_event_id     BIGINT        NULL REFERENCES wf.events(event_id),
    started_by_user_id   INT           NULL REFERENCES sec.users(user_id),
    started_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    ended_at             TIMESTAMPTZ   NULL,
    row_version          INT           NOT NULL DEFAULT 1,
    step_count           INT           NOT NULL DEFAULT 0,
    depth                SMALLINT      NOT NULL DEFAULT 0,
    last_error           TEXT          NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_wf_instances_correlation ON wf.instances (company_id, correlation_key) WHERE correlation_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_wf_instances_entity ON wf.instances (company_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_wf_instances_status ON wf.instances (company_id, status_code);

-- لاگ اجرای هر گره (Observability + Timeline)
CREATE TABLE IF NOT EXISTS wf.instance_steps (
    step_id         BIGSERIAL     PRIMARY KEY,
    instance_id     BIGINT        NOT NULL REFERENCES wf.instances(instance_id) ON DELETE CASCADE,
    node_id         VARCHAR(40)   NOT NULL,
    node_type       VARCHAR(20)   NOT NULL,
    label           VARCHAR(200)  NULL,
    status_code     VARCHAR(10)   NOT NULL DEFAULT 'RUNNING'
        CHECK (status_code IN ('RUNNING', 'DONE', 'WAITING', 'FAILED', 'SKIPPED')),
    outcome         VARCHAR(30)   NULL,
    attempt         SMALLINT      NOT NULL DEFAULT 1,
    actor_user_id   INT           NULL REFERENCES sec.users(user_id),
    detail          JSONB         NOT NULL DEFAULT '{}'::jsonb,
    error           TEXT          NULL,
    started_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ   NULL,
    duration_ms     INT           NULL
);
CREATE INDEX IF NOT EXISTS ix_wf_instance_steps_instance ON wf.instance_steps (instance_id, step_id);

-- دفترِ اجرای اقدام‌ها: کلیدِ یکتا جلوی اجرای دوبارهٔ اقدامِ حساس در Retry/رویدادِ تکراری را می‌گیرد
CREATE TABLE IF NOT EXISTS wf.action_executions (
    execution_id     BIGSERIAL     PRIMARY KEY,
    company_id       INT           NOT NULL REFERENCES core.companies(company_id),
    instance_id      BIGINT        NULL REFERENCES wf.instances(instance_id) ON DELETE CASCADE,
    node_id          VARCHAR(40)   NULL,
    idempotency_key  VARCHAR(200)  NOT NULL,
    action_code      VARCHAR(80)   NOT NULL,
    status_code      VARCHAR(10)   NOT NULL DEFAULT 'PENDING' CHECK (status_code IN ('PENDING', 'DONE', 'FAILED')),
    attempts         SMALLINT      NOT NULL DEFAULT 0,
    next_retry_at    TIMESTAMPTZ   NULL,
    result           JSONB         NOT NULL DEFAULT '{}'::jsonb,
    last_error       TEXT          NULL,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (company_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS wf.exceptions (
    exception_id        BIGSERIAL     PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    instance_id         BIGINT        NULL REFERENCES wf.instances(instance_id) ON DELETE CASCADE,
    node_id             VARCHAR(40)   NULL,
    execution_id        BIGINT        NULL REFERENCES wf.action_executions(execution_id) ON DELETE SET NULL,
    title               VARCHAR(300)  NOT NULL,
    reason              TEXT          NOT NULL,
    technical_detail    TEXT          NULL,
    priority_code       VARCHAR(10)   NOT NULL DEFAULT 'HIGH',
    owner_user_id       INT           NULL REFERENCES sec.users(user_id),
    owner_role_id       INT           NULL REFERENCES sec.roles(role_id),
    status_code         VARCHAR(10)   NOT NULL DEFAULT 'OPEN'
        CHECK (status_code IN ('OPEN', 'RETRYING', 'RESOLVED', 'IGNORED', 'ESCALATED')),
    resolution_note     VARCHAR(1000) NULL,
    resolved_by_user_id INT           NULL REFERENCES sec.users(user_id),
    resolved_at         TIMESTAMPTZ   NULL,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_wf_exceptions_open ON wf.exceptions (company_id, status_code);

-- زمان‌سنج‌ها (انتظار، تلاشِ دوباره، یادآوری، Escalation): اجرای امن چندکلاینتی با locked_until و SKIP LOCKED
CREATE TABLE IF NOT EXISTS wf.timers (
    timer_id      BIGSERIAL     PRIMARY KEY,
    company_id    INT           NOT NULL REFERENCES core.companies(company_id),
    kind          VARCHAR(12)   NOT NULL CHECK (kind IN ('WAIT', 'RETRY', 'REMINDER', 'ESCALATION', 'SLA', 'SCAN')),
    instance_id   BIGINT        NULL REFERENCES wf.instances(instance_id) ON DELETE CASCADE,
    task_id       BIGINT        NULL,
    node_id       VARCHAR(40)   NULL,
    payload       JSONB         NOT NULL DEFAULT '{}'::jsonb,
    due_at        TIMESTAMPTZ   NOT NULL,
    status_code   VARCHAR(10)   NOT NULL DEFAULT 'PENDING' CHECK (status_code IN ('PENDING', 'DONE', 'CANCELLED', 'FAILED')),
    locked_until  TIMESTAMPTZ   NULL,
    attempts      SMALLINT      NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    fired_at      TIMESTAMPTZ   NULL
);
CREATE INDEX IF NOT EXISTS ix_wf_timers_due ON wf.timers (due_at) WHERE status_code = 'PENDING';
CREATE INDEX IF NOT EXISTS ix_wf_timers_instance ON wf.timers (instance_id);

-- تنظیمات کلی موتور به ازای شرکت (اجازهٔ خودتاییدی، فهرست مجاز سرویس‌های بیرونی، ...)
CREATE TABLE IF NOT EXISTS wf.settings (
    company_id  INT          PRIMARY KEY REFERENCES core.companies(company_id),
    options     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- حسابرسی اقدام‌های گردش کار با نام واقعی خودشان (به‌جای تبدیل همه به UPDATE)
ALTER TABLE audit.activity_log DROP CONSTRAINT IF EXISTS ck_activity_log_action;
ALTER TABLE audit.activity_log ADD CONSTRAINT ck_activity_log_action
    CHECK (action IN ('CREATE', 'UPDATE', 'DELETE', 'APPROVE', 'REVERSE', 'MERGE',
                      'SUBMIT', 'REJECT', 'DELEGATE', 'ESCALATE', 'EXECUTE', 'PUBLISH', 'CANCEL', 'RETRY',
                      'RESOLVE', 'COMMENT', 'START', 'COMPLETE'));
