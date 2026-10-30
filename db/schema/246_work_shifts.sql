-- پیچا | R359: شیفت کاری و واگذاری شیفت به کارکنان (با تاریخ شروع)؛ تأخیر، تعجیل و غیبت از حضور و غیاب محاسبه می‌شود
CREATE TABLE IF NOT EXISTS hr.work_shifts (
    shift_id        INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES core.companies(company_id),
    code            VARCHAR(20)  NOT NULL,
    name            VARCHAR(100) NOT NULL,
    start_time      TIME         NOT NULL,
    end_time        TIME         NOT NULL,
    break_minutes   INT          NOT NULL DEFAULT 0 CHECK (break_minutes >= 0),
    grace_minutes   INT          NOT NULL DEFAULT 0 CHECK (grace_minutes >= 0),
    off_weekdays    VARCHAR(20)  NOT NULL DEFAULT '4',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_hr_work_shifts UNIQUE (company_id, code),
    CONSTRAINT ck_hr_work_shifts_time CHECK (end_time > start_time)
);

CREATE TABLE IF NOT EXISTS hr.employee_shift_assignments (
    assignment_id   INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES core.companies(company_id),
    employee_id     INT          NOT NULL REFERENCES hr.employees(employee_id) ON DELETE CASCADE,
    shift_id        INT          NOT NULL REFERENCES hr.work_shifts(shift_id),
    valid_from      DATE         NOT NULL,
    CONSTRAINT uq_hr_employee_shift UNIQUE (employee_id, valid_from)
);
