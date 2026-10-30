-- پیچا | R367: جذب و استخدام — فرصت شغلی روی پست سازمانی، متقاضی، مراحل درخواست با سابقه، مصاحبه و استخدام به پروندهٔ پرسنلی
CREATE TABLE IF NOT EXISTS hr.job_openings (
    opening_id                  INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id                  INT           NOT NULL REFERENCES core.companies(company_id),
    code                        VARCHAR(30)   NOT NULL,
    title                       VARCHAR(200)  NOT NULL,
    position_id                 INT           NOT NULL REFERENCES hr.positions(position_id),
    headcount                   INT           NOT NULL DEFAULT 1 CHECK (headcount >= 1),
    status_code                 VARCHAR(20)   NOT NULL DEFAULT 'OPEN' CHECK (status_code IN ('OPEN', 'ON_HOLD', 'CLOSED', 'FILLED')),
    opened_on                   DATE          NOT NULL,
    close_by                    DATE,
    salary_min                  NUMERIC(18,2),
    salary_max                  NUMERIC(18,2),
    hiring_manager_employee_id  INT           REFERENCES hr.employees(employee_id) ON DELETE SET NULL,
    description                 VARCHAR(2000),
    requirements                VARCHAR(2000),
    created_by_user_id          INT           REFERENCES sec.users(user_id),
    created_at                  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT uq_hr_job_openings UNIQUE (company_id, code),
    CONSTRAINT ck_hr_job_openings_salary CHECK (salary_min IS NULL OR salary_max IS NULL OR salary_max >= salary_min)
);

CREATE TABLE IF NOT EXISTS hr.candidates (
    candidate_id      INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id        INT           NOT NULL REFERENCES core.companies(company_id),
    first_name        VARCHAR(100)  NOT NULL,
    last_name         VARCHAR(100)  NOT NULL,
    national_id       VARCHAR(20),
    mobile            VARCHAR(30),
    email             VARCHAR(150),
    education         VARCHAR(200),
    experience_years  NUMERIC(4,1),
    source_code       VARCHAR(20)   NOT NULL DEFAULT 'OTHER'
        CHECK (source_code IN ('WEBSITE', 'JOB_BOARD', 'REFERRAL', 'AGENCY', 'CAMPUS', 'OTHER')),
    notes             VARCHAR(1000),
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hr_candidates_national ON hr.candidates(company_id, national_id) WHERE national_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS hr.job_applications (
    application_id     INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id         INT           NOT NULL REFERENCES core.companies(company_id),
    opening_id         INT           NOT NULL REFERENCES hr.job_openings(opening_id),
    candidate_id       INT           NOT NULL REFERENCES hr.candidates(candidate_id),
    stage_code         VARCHAR(20)   NOT NULL DEFAULT 'APPLIED'
        CHECK (stage_code IN ('APPLIED', 'SCREENING', 'INTERVIEW', 'OFFER', 'HIRED', 'REJECTED', 'WITHDRAWN')),
    applied_on         DATE          NOT NULL,
    offer_salary       NUMERIC(18,2),
    offer_start_date   DATE,
    decision_note      VARCHAR(500),
    employee_id        INT           REFERENCES hr.employees(employee_id),
    hired_on           DATE,
    CONSTRAINT uq_hr_job_applications UNIQUE (opening_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS hr.application_events (
    event_id        INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id  INT          NOT NULL REFERENCES hr.job_applications(application_id) ON DELETE CASCADE,
    from_stage      VARCHAR(20),
    to_stage        VARCHAR(20)  NOT NULL,
    note            VARCHAR(500),
    user_id         INT          REFERENCES sec.users(user_id),
    at              TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hr.interviews (
    interview_id              INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id            INT          NOT NULL REFERENCES hr.job_applications(application_id) ON DELETE CASCADE,
    scheduled_at              TIMESTAMPTZ  NOT NULL,
    interviewer_employee_id   INT          REFERENCES hr.employees(employee_id) ON DELETE SET NULL,
    mode_code                 VARCHAR(20)  NOT NULL DEFAULT 'IN_PERSON' CHECK (mode_code IN ('IN_PERSON', 'PHONE', 'VIDEO')),
    status_code               VARCHAR(20)  NOT NULL DEFAULT 'SCHEDULED' CHECK (status_code IN ('SCHEDULED', 'DONE', 'CANCELLED')),
    score                     SMALLINT     CHECK (score BETWEEN 1 AND 5),
    recommendation_code       VARCHAR(20)  CHECK (recommendation_code IN ('HIRE', 'MAYBE', 'NO')),
    notes                     VARCHAR(1000)
);
