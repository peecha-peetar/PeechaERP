-- پیچا | حضوروغیابِ واقعی: ثبتِ روزانهٔ ورود/خروجِ کارکنان + خلاصهٔ کارکرد
-- + الگوهایِ ذخیره‌شدهٔ ایمپورتِ فایلِ اکسل/CSVِ دستگاه‌هایِ حضوروغیاب.
--
-- طبقِ گزارشِ صریحِ کاربر: تا این نسخه، «کارکردِ پرسنل» فقط به‌صورتِ ثبتِ
-- دستیِ ساعاتِ اضافه‌کاری (payroll.overtime_entries) موجود بود، نه ثبتِ
-- واقعیِ ورود/خروجِ روزانه. این جدول همان زیرساختِ حضوروغیابِ واقعی است که
-- در یادداشتِ schema 046 به‌عنوانِ «خارج از اسکوپِ آن فاز» مشخص شده بود.

CREATE TABLE hr.attendance_records (
    attendance_id   INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES core.companies(company_id),
    employee_id     INT          NOT NULL REFERENCES hr.employees(employee_id),
    work_date       DATE         NOT NULL,
    clock_in        TIME,
    clock_out       TIME,
    worked_hours    NUMERIC(6,2),
    status          VARCHAR(20)  NOT NULL DEFAULT 'PENDING_APPROVAL' CHECK (status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED')),
    source          VARCHAR(20)  NOT NULL DEFAULT 'MANUAL' CHECK (source IN ('MANUAL', 'IMPORT')),
    notes           VARCHAR(300),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_hr_attendance_records UNIQUE (employee_id, work_date),
    CONSTRAINT ck_hr_attendance_records_time CHECK (clock_in IS NULL OR clock_out IS NULL OR clock_out > clock_in),
    CONSTRAINT ck_hr_attendance_records_source CHECK (
        worked_hours IS NOT NULL OR (clock_in IS NOT NULL AND clock_out IS NOT NULL)
    )
);

CREATE INDEX ix_hr_attendance_records_company_date ON hr.attendance_records(company_id, work_date);

-- الگویِ ذخیره‌شدهٔ تناظرِ ستون‌هایِ فایلِ اکسل/CSVِ خروجیِ دستگاهِ
-- حضوروغیابِ یک شرکتِ سازنده — طبقِ خواستهٔ صریح («الگویِ فایلِ csv
-- شرکت‌هایِ دستگاه‌دار حضوروغیاب تعریف کنم») تا دفعاتِ بعد فقط مسیرِ
-- فایل انتخاب شود، بدونِ نیاز به تناظرِ دستیِ ستون‌ها.
CREATE TABLE hr.attendance_import_templates (
    template_id     INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id      INT          NOT NULL REFERENCES core.companies(company_id),
    name            VARCHAR(150) NOT NULL,
    has_header_row  BOOLEAN      NOT NULL DEFAULT TRUE,
    date_format     VARCHAR(30)  NOT NULL DEFAULT '%Y-%m-%d',
    time_format     VARCHAR(30)  NOT NULL DEFAULT '%H:%M',
    column_mapping  JSONB        NOT NULL DEFAULT '{}'::jsonb,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_hr_attendance_import_templates UNIQUE (company_id, name)
);
