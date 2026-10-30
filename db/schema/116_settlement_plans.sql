-- طبقِ درخواستِ صریح: دکمه‌یِ «نحوهٔ تسویه» در فرمِ فاکتور -- نقشه‌یِ
-- ترکیبیِ تسویه (نقد/بانک(کارتخوان)/بن/کالابرگ/تخفیف + مانده به‌عنوانِ
-- نسیه) که با فاکتور نگهداری می‌شود و پیش از ثبتِ نهایی نیازِ تاییدِ
-- مدیر دارد.

CREATE TABLE comm.commercial_document_settlement_plans (
    plan_id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    document_id BIGINT NOT NULL UNIQUE REFERENCES comm.commercial_documents(document_id),
    status_code VARCHAR(20) NOT NULL DEFAULT 'PENDING_APPROVAL'
        CHECK (status_code IN ('PENDING_APPROVAL', 'APPROVED')),
    total_amount NUMERIC(18, 2) NOT NULL,
    created_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by_user_id INT REFERENCES sec.users(user_id),
    approved_at TIMESTAMPTZ
);

CREATE TABLE comm.commercial_document_settlement_plan_lines (
    line_id BIGSERIAL PRIMARY KEY,
    plan_id BIGINT NOT NULL REFERENCES comm.commercial_document_settlement_plans(plan_id) ON DELETE CASCADE,
    method_code VARCHAR(30) NOT NULL,
    amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    note VARCHAR(200),
    display_order SMALLINT NOT NULL DEFAULT 0
);

CREATE INDEX idx_settlement_plan_lines_plan_id ON comm.commercial_document_settlement_plan_lines(plan_id);
