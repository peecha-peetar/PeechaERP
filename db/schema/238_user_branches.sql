-- پیچا | R350: محدودیت دسترسی کاربر به شعبه‌ها (هر شرکت جدا)؛ کاربری که ردیفی ندارد به همهٔ شعبه‌ها دسترسی دارد
-- پیش‌نیاز: 002_security_rbac.sql، comm.branches

CREATE TABLE IF NOT EXISTS sec.user_branches (
    user_id     INT NOT NULL REFERENCES sec.users(user_id),
    company_id  INT NOT NULL REFERENCES core.companies(company_id),
    branch_id   INT NOT NULL REFERENCES comm.branches(branch_id),
    PRIMARY KEY (user_id, company_id, branch_id)
);
