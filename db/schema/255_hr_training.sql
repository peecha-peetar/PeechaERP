-- پیچا | R369: آموزش — دوره‌ها، دوره‌های الزامی هر پست، کلاس‌ها، ثبت‌نام، نتیجه و گواهی با تاریخ انقضا
CREATE TABLE IF NOT EXISTS hr.training_courses (
    course_id        INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id       INT           NOT NULL REFERENCES core.companies(company_id),
    code             VARCHAR(30)   NOT NULL,
    title            VARCHAR(200)  NOT NULL,
    category_code    VARCHAR(20)   NOT NULL DEFAULT 'OTHER'
        CHECK (category_code IN ('SAFETY', 'TECHNICAL', 'QUALITY', 'SOFT_SKILLS', 'COMPLIANCE', 'OTHER')),
    hours            NUMERIC(6,1)  NOT NULL CHECK (hours > 0),
    validity_months  INT           CHECK (validity_months IS NULL OR validity_months > 0),
    provider         VARCHAR(200),
    is_active        BOOLEAN       NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_hr_training_courses UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS hr.position_trainings (
    position_id  INT  NOT NULL REFERENCES hr.positions(position_id) ON DELETE CASCADE,
    course_id    INT  NOT NULL REFERENCES hr.training_courses(course_id) ON DELETE CASCADE,
    PRIMARY KEY (position_id, course_id)
);

CREATE TABLE IF NOT EXISTS hr.training_sessions (
    session_id   INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id   INT           NOT NULL REFERENCES core.companies(company_id),
    course_id    INT           NOT NULL REFERENCES hr.training_courses(course_id),
    start_date   DATE          NOT NULL,
    end_date     DATE          NOT NULL,
    trainer      VARCHAR(200),
    location     VARCHAR(200),
    capacity     INT           CHECK (capacity IS NULL OR capacity > 0),
    cost         NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (cost >= 0),
    status_code  VARCHAR(20)   NOT NULL DEFAULT 'PLANNED' CHECK (status_code IN ('PLANNED', 'COMPLETED', 'CANCELLED')),
    CONSTRAINT ck_hr_training_sessions_dates CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS hr.training_enrollments (
    enrollment_id   INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id      INT           NOT NULL REFERENCES hr.training_sessions(session_id) ON DELETE CASCADE,
    employee_id     INT           NOT NULL REFERENCES hr.employees(employee_id),
    status_code     VARCHAR(20)   NOT NULL DEFAULT 'ENROLLED' CHECK (status_code IN ('ENROLLED', 'ATTENDED', 'PASSED', 'FAILED', 'ABSENT')),
    score           NUMERIC(5,2)  CHECK (score IS NULL OR score BETWEEN 0 AND 100),
    certificate_no  VARCHAR(50),
    completed_on    DATE,
    expires_on      DATE,
    CONSTRAINT uq_hr_training_enrollments UNIQUE (session_id, employee_id)
);
