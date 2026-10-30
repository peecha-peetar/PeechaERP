-- پیچا | R373: سناریوی تقاضا و تامین برای بررسی تعهد تحویل (ATP) — فقط شبیه‌سازی؛ در سفارش‌ها و دستورها چیزی ثبت نمی‌شود
CREATE TABLE IF NOT EXISTS prd.atp_scenarios (
    scenario_id         INT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id          INT           NOT NULL REFERENCES core.companies(company_id),
    name                VARCHAR(150)  NOT NULL,
    description         VARCHAR(500),
    created_by_user_id  INT           REFERENCES sec.users(user_id),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT uq_prd_atp_scenarios_name UNIQUE (company_id, name)
);

CREATE TABLE IF NOT EXISTS prd.atp_scenario_lines (
    line_id      INT            GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scenario_id  INT            NOT NULL REFERENCES prd.atp_scenarios(scenario_id) ON DELETE CASCADE,
    item_id      INT            NOT NULL REFERENCES inv.items(item_id),
    kind_code    VARCHAR(10)    NOT NULL CHECK (kind_code IN ('DEMAND', 'SUPPLY')),
    line_date    DATE           NOT NULL,
    quantity     NUMERIC(18,6)  NOT NULL CHECK (quantity > 0),
    note         VARCHAR(300)
);
