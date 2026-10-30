-- پیچا | R366: درخواست تغییر پروژه (مبلغ، مدت و ردیف‌های جدید فهرست بها) با تایید
CREATE TABLE IF NOT EXISTS prj.change_orders (
    change_id            INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id           INT           NOT NULL REFERENCES core.companies(company_id),
    project_id           INT           NOT NULL REFERENCES prj.projects(project_id),
    change_no            INT           NOT NULL,
    title                VARCHAR(200)  NOT NULL,
    reason               VARCHAR(1000),
    amount_change        NUMERIC(18,2) NOT NULL DEFAULT 0,
    days_change          INT           NOT NULL DEFAULT 0,
    status_code          VARCHAR(20)   NOT NULL DEFAULT 'DRAFT' CHECK (status_code IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED')),
    decision_note        VARCHAR(500),
    requested_by_user_id INT           REFERENCES sec.users(user_id),
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    decided_by_user_id   INT           REFERENCES sec.users(user_id),
    decided_at           TIMESTAMPTZ,
    CONSTRAINT uq_prj_change_orders UNIQUE (project_id, change_no)
);

CREATE TABLE IF NOT EXISTS prj.change_order_lines (
    line_id           INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    change_id         INT           NOT NULL REFERENCES prj.change_orders(change_id) ON DELETE CASCADE,
    code              VARCHAR(30)   NOT NULL,
    description       VARCHAR(300)  NOT NULL,
    unit              VARCHAR(30)   NOT NULL,
    quantity          NUMERIC(18,3) NOT NULL CHECK (quantity > 0),
    unit_price        NUMERIC(18,2) NOT NULL CHECK (unit_price >= 0),
    contract_item_id  INT           REFERENCES prj.contract_items(contract_item_id) ON DELETE SET NULL
);
