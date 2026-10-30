-- پیچا | R368: ارزیابی عملکرد — قالب معیارها با وزن، دورهٔ ارزیابی، خودارزیابی و ارزیابی مدیر، امتیاز وزنی و نهایی‌شدن
CREATE TABLE IF NOT EXISTS hr.appraisal_templates (
    template_id  INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id   INT           NOT NULL REFERENCES core.companies(company_id),
    code         VARCHAR(30)   NOT NULL,
    name         VARCHAR(200)  NOT NULL,
    is_active    BOOLEAN       NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_hr_appraisal_templates UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS hr.appraisal_criteria (
    criterion_id  INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    template_id   INT           NOT NULL REFERENCES hr.appraisal_templates(template_id) ON DELETE CASCADE,
    title         VARCHAR(200)  NOT NULL,
    description   VARCHAR(500),
    weight        NUMERIC(5,2)  NOT NULL CHECK (weight > 0),
    sort_order    INT           NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS hr.appraisal_cycles (
    cycle_id         INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id       INT           NOT NULL REFERENCES core.companies(company_id),
    title            VARCHAR(200)  NOT NULL,
    template_id      INT           NOT NULL REFERENCES hr.appraisal_templates(template_id),
    period_from      DATE          NOT NULL,
    period_to        DATE          NOT NULL,
    self_assessment  BOOLEAN       NOT NULL DEFAULT TRUE,
    status_code      VARCHAR(20)   NOT NULL DEFAULT 'DRAFT' CHECK (status_code IN ('DRAFT', 'OPEN', 'CLOSED')),
    CONSTRAINT ck_hr_appraisal_cycles_period CHECK (period_to >= period_from)
);

CREATE TABLE IF NOT EXISTS hr.appraisals (
    appraisal_id           INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id             INT           NOT NULL REFERENCES core.companies(company_id),
    cycle_id               INT           NOT NULL REFERENCES hr.appraisal_cycles(cycle_id) ON DELETE CASCADE,
    employee_id            INT           NOT NULL REFERENCES hr.employees(employee_id),
    reviewer_employee_id   INT           REFERENCES hr.employees(employee_id) ON DELETE SET NULL,
    status_code            VARCHAR(20)   NOT NULL DEFAULT 'PENDING_SELF'
        CHECK (status_code IN ('PENDING_SELF', 'PENDING_MANAGER', 'REVIEWED', 'FINALIZED')),
    self_comment           VARCHAR(1000),
    manager_comment        VARCHAR(1000),
    strengths              VARCHAR(1000),
    improvements           VARCHAR(1000),
    goals                  VARCHAR(1000),
    overall_score          NUMERIC(4,2),
    finalized_by_user_id   INT           REFERENCES sec.users(user_id),
    finalized_at           TIMESTAMPTZ,
    CONSTRAINT uq_hr_appraisals UNIQUE (cycle_id, employee_id)
);

CREATE TABLE IF NOT EXISTS hr.appraisal_scores (
    appraisal_id   INT           NOT NULL REFERENCES hr.appraisals(appraisal_id) ON DELETE CASCADE,
    criterion_id   INT           NOT NULL REFERENCES hr.appraisal_criteria(criterion_id),
    self_score     SMALLINT      CHECK (self_score BETWEEN 1 AND 5),
    manager_score  SMALLINT      CHECK (manager_score BETWEEN 1 AND 5),
    comment        VARCHAR(500),
    PRIMARY KEY (appraisal_id, criterion_id)
);
