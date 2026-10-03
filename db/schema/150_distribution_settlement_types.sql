-- طبقِ اصلاحِ صریحِ کاربر: «نوعِ تسویه»یِ پخشِ سرد (تسویهٔ نقدیِ پایِ بار/
-- چک/رسید/یک‌هفته‌ای/پایِ بار و...) کاملاً مفهومی جدا از «نوعِ تسویه»یِ
-- خزانه‌داری (روشِ دریافت/پرداختِ حسابداری) است -- این‌جا یک جدولِ
-- تازه و مستقل، قابلِ‌تعریفِ کاربر، هم‌الگو با comm.channels (کلیدِ
-- طبیعیِ code + company_id، نه شناسهٔ خودکار).

CREATE TABLE comm.distribution_settlement_types (
    code VARCHAR(20) NOT NULL,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    name VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (code, company_id)
);
