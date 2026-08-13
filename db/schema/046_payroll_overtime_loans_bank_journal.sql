-- پیچا | فازِ ۴ از ماژولِ حقوق و دستمزد: اضافه‌کاری (فصلِ ۱۲)، وام/مساعده
-- (فصلِ ۱۳)، فایلِ بانکی (فصلِ ۱۵)، و پیوندِ سندِ حسابداریِ خودکار (فصلِ ۱۶).
--
-- ⚠ ساده‌سازیِ آگاهانه: فصلِ ۱۲ در سند بر رویِ hr.attendance_records بنا
--   می‌شود، ولی هستهٔ منابعِ انسانیِ فعلیِ Peecha (فازِ ۱) حضوروغیاب/شیفت
--   را پیاده‌سازی نکرده (خارج از اسکوپِ آن فاز بود). به‌جایِ ساختِ کاملِ
--   زیرساختِ حضوروغیاب/شیفت (که خودش یک فازِ کاملاً جداست)، ساعاتِ هر نوعِ
--   اضافه‌کاری به‌صورتِ «ثبتِ دستی به‌ازایِ کارمند/دوره» دریافت می‌شود —
--   منطقِ نرخِ ساعتی + ترکیبِ ضرایب (که هستهٔ فنیِ واقعیِ این فصل است)
--   دقیقاً طبقِ سند پیاده می‌شود؛ فقط منبعِ «چند ساعت» به‌جایِ استخراجِ
--   خودکار از حضوروغیاب، ورودیِ دستی است.

CREATE TABLE payroll.overtime_rules (
    overtime_rule_id       INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id             INT          NOT NULL REFERENCES core.companies(company_id),
    code                   VARCHAR(30)  NOT NULL CHECK (code IN ('OVERTIME', 'NIGHT_SHIFT', 'HOLIDAY_WORK', 'FRIDAY_WORK', 'ROTATING_SHIFT_BONUS')),
    multiplier             NUMERIC(6,4) NOT NULL CHECK (multiplier >= 1),
    stacking_mode          VARCHAR(20)  NOT NULL DEFAULT 'ADDITIVE' CHECK (stacking_mode IN ('ADDITIVE', 'MULTIPLICATIVE', 'MAX_ONLY')),
    max_monthly_hours_policy_code VARCHAR(60),
    effective_from         DATE         NOT NULL,
    effective_to           DATE,
    CONSTRAINT uq_payroll_overtime_rules UNIQUE (company_id, code, effective_from),
    CONSTRAINT ck_payroll_overtime_rules_dates CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

-- ثبتِ دستیِ ساعاتِ هر نوعِ اضافه‌کاری برایِ یک کارمند در یک دوره (طبقِ
-- یادداشتِ بالا، جایگزینِ استخراجِ خودکار از حضوروغیاب)
CREATE TABLE payroll.overtime_entries (
    overtime_entry_id INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id        INT          NOT NULL REFERENCES hr.employees(employee_id),
    period_id          INT          NOT NULL REFERENCES payroll.periods(period_id),
    overtime_rule_id   INT          NOT NULL REFERENCES payroll.overtime_rules(overtime_rule_id),
    hours              NUMERIC(7,2) NOT NULL CHECK (hours > 0),
    status             VARCHAR(20)  NOT NULL DEFAULT 'PENDING_APPROVAL' CHECK (status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED')),
    CONSTRAINT uq_payroll_overtime_entries UNIQUE (employee_id, period_id, overtime_rule_id)
);

-- ---------------------------------------------------------------------
-- وام و مساعده (فصلِ ۱۳)
-- ---------------------------------------------------------------------
CREATE TABLE payroll.loans (
    loan_id              INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id          INT          NOT NULL REFERENCES hr.employees(employee_id),
    loan_type            VARCHAR(10)  NOT NULL CHECK (loan_type IN ('LOAN', 'ADVANCE')),
    principal_amount     NUMERIC(18,2) NOT NULL CHECK (principal_amount > 0),
    fee_rate             NUMERIC(6,4) NOT NULL DEFAULT 0,
    installments_count   SMALLINT     NOT NULL CHECK (installments_count >= 1),
    start_period_id      INT          NOT NULL REFERENCES payroll.periods(period_id),
    funding_source       VARCHAR(50),
    status               VARCHAR(20)  NOT NULL DEFAULT 'REQUESTED' CHECK (status IN ('REQUESTED', 'APPROVED', 'DISBURSED', 'ACTIVE', 'SETTLED', 'REJECTED', 'CANCELLED')),
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_payroll_loans_employee ON payroll.loans(employee_id);

CREATE TABLE payroll.loan_installments (
    loan_installment_id INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    loan_id               INT          NOT NULL REFERENCES payroll.loans(loan_id),
    installment_no        SMALLINT     NOT NULL,
    due_period_id         INT          NOT NULL REFERENCES payroll.periods(period_id),
    amount                NUMERIC(18,2) NOT NULL,
    status                VARCHAR(20)  NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'DEDUCTED', 'DEFERRED', 'WAIVED')),
    CONSTRAINT uq_payroll_loan_installments UNIQUE (loan_id, installment_no)
);
CREATE INDEX ix_payroll_loan_installments_due ON payroll.loan_installments(due_period_id, status);

-- ---------------------------------------------------------------------
-- فایلِ بانکیِ پرداختِ گروهی (فصلِ ۱۵) — بدونِ قالبِ اختصاصیِ هیچ بانکی
-- (نبودِ مشخصاتِ رسمی)؛ خروجی به‌صورتِ CSV عمومی است.
-- ---------------------------------------------------------------------
CREATE TABLE payroll.bank_payment_batches (
    batch_id           INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id             INT          NOT NULL REFERENCES payroll.runs(run_id),
    bank_id            INT          NOT NULL REFERENCES treasury.banks(bank_id),
    total_amount       NUMERIC(18,2) NOT NULL,
    status             VARCHAR(20)  NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SENT', 'CONFIRMED')),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE payroll.bank_payment_lines (
    line_id              INT          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id              INT          NOT NULL REFERENCES payroll.bank_payment_batches(batch_id),
    payslip_id             INT          NOT NULL REFERENCES payroll.payslips(payslip_id),
    employee_id            INT          NOT NULL REFERENCES hr.employees(employee_id),
    bank_account_no        VARCHAR(40)  NOT NULL,
    amount                 NUMERIC(18,2) NOT NULL,
    line_status            VARCHAR(20)  NOT NULL DEFAULT 'PENDING' CHECK (line_status IN ('PENDING', 'SENT', 'CONFIRMED', 'FAILED'))
);

-- ---------------------------------------------------------------------
-- پیوندِ سندِ حسابداریِ خودکار (فصلِ ۱۶)
-- ---------------------------------------------------------------------
CREATE TABLE payroll.journal_entry_links (
    run_id             INT NOT NULL REFERENCES payroll.runs(run_id) PRIMARY KEY,
    journal_entry_id   INT NOT NULL REFERENCES acc.journal_entries(journal_entry_id)
);

-- نوعِ سندِ تازه برایِ اسنادِ خودکارِ حقوق (هم‌الگو با ۰۲۲: RECEIPT/PAYMENT)
INSERT INTO acc.journal_entry_types (entry_type_id, code) VALUES
    (7, 'PAYROLL')
ON CONFLICT (entry_type_id) DO NOTHING;
