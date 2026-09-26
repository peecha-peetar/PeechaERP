-- طبقِ درخواستِ صریح («فاکتورهایِ صادر شده تا قبل از ثبتِ سند توسطِ
-- صندوق‌دار هم بتونه حذف و اصلاح کنه و در هنگامِ بستنِ شیفت، فاکتورهایِ
-- اصلاح‌شده و حذف‌شده به سرپرست گزارش بشه»): وقتی صندوق‌دار یک فاکتورِ
-- تاییدشده (CONFIRMED) را قبل از تاییدِ سرپرست دوباره بازمی‌کند (برایِ
-- اصلاح) یا لغو می‌کند (حذف)، همین‌جا ثبت می‌شود -- تا هنگامِ بستنِ
-- شیفت (comm.pos_sessions) بتوان فهرستِ این تغییرات را به سرپرست نشان
-- داد.

CREATE TABLE comm.pos_invoice_audit_log (
    audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    pos_session_id BIGINT NOT NULL REFERENCES comm.pos_sessions(session_id),
    document_id BIGINT NOT NULL REFERENCES comm.commercial_documents(document_id),
    action_code VARCHAR(20) NOT NULL CHECK (action_code IN ('REOPENED', 'DELETED')),
    performed_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    performed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    note VARCHAR(300)
);

CREATE INDEX idx_pos_invoice_audit_log_session ON comm.pos_invoice_audit_log(pos_session_id);
