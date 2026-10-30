-- R382: کالیبراسیون ابزار اندازه‌گیری — فهرست ابزار، دورهٔ کالیبراسیون، سابقهٔ نتیجه و سررسید.
-- ابزار ردشده از خدمت خارج می‌شود و (به انتخاب کاربر) یک عدم‌انطباق کیفیت برای بررسی اندازه‌گیری‌های قبلی باز می‌شود.
CREATE TABLE IF NOT EXISTS mnt.calibration_instruments (
    instrument_id          BIGSERIAL      PRIMARY KEY,
    company_id             INT            NOT NULL REFERENCES core.companies(company_id),
    code                   VARCHAR(30)    NOT NULL,
    name                   VARCHAR(200)   NOT NULL,
    asset_id               BIGINT         NULL REFERENCES fa.assets(asset_id),
    serial_no              VARCHAR(100)   NULL,
    location_text          VARCHAR(200)   NULL,
    measure_range          VARCHAR(100)   NULL,
    tolerance              VARCHAR(100)   NULL,
    interval_days          INT            NOT NULL CHECK (interval_days > 0),
    lead_days              INT            NOT NULL DEFAULT 14 CHECK (lead_days >= 0),
    method_code            VARCHAR(10)    NOT NULL DEFAULT 'EXTERNAL' CHECK (method_code IN ('INTERNAL', 'EXTERNAL')),
    lab_detail_account_id  INT            NULL REFERENCES acc.detail_accounts(detail_account_id),
    responsible_user_id    INT            NULL REFERENCES sec.users(user_id),
    status_code            VARCHAR(15)    NOT NULL DEFAULT 'ACTIVE' CHECK (status_code IN ('ACTIVE', 'OUT_OF_SERVICE', 'RETIRED')),
    next_due_date          DATE           NOT NULL,
    last_calibrated_on     DATE           NULL,
    notes                  VARCHAR(1000)  NULL,
    created_by_user_id     INT            NULL REFERENCES sec.users(user_id),
    created_at             TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CONSTRAINT uq_mnt_calibration_instruments UNIQUE (company_id, code)
);
CREATE INDEX IF NOT EXISTS ix_mnt_calibration_due ON mnt.calibration_instruments (company_id, status_code, next_due_date);

CREATE TABLE IF NOT EXISTS mnt.calibration_records (
    record_id           BIGSERIAL      PRIMARY KEY,
    company_id          INT            NOT NULL REFERENCES core.companies(company_id),
    instrument_id       BIGINT         NOT NULL REFERENCES mnt.calibration_instruments(instrument_id) ON DELETE CASCADE,
    record_no           INT            NOT NULL,
    calibrated_on       DATE           NOT NULL,
    result_code         VARCHAR(10)    NOT NULL CHECK (result_code IN ('PASS', 'ADJUSTED', 'FAIL')),
    performed_by        VARCHAR(200)   NULL,
    certificate_no      VARCHAR(100)   NULL,
    as_found            VARCHAR(500)   NULL,
    as_left             VARCHAR(500)   NULL,
    cost_amount         NUMERIC(18,2)  NOT NULL DEFAULT 0 CHECK (cost_amount >= 0),
    next_due_date       DATE           NULL,
    ncr_id              INT            NULL REFERENCES qms.nonconformances(ncr_id) ON DELETE SET NULL,
    notes               VARCHAR(1000)  NULL,
    created_by_user_id  INT            NULL REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT now(),
    CONSTRAINT uq_mnt_calibration_records UNIQUE (company_id, record_no)
);
