-- طبقِ درخواستِ صریح: در فرمِ افزودنِ پرداختِ سفارش، یک فیلدِ جداگانه‌یِ
-- «عنوانِ پرداخت» (مثلاً «هزینه‌یِ ترخیص»، «بهایِ اولیه‌یِ کالا») از یک
-- فهرستِ قابلِ‌گسترش انتخاب شود.

CREATE TABLE comm.order_payment_titles (
    payment_title_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    label VARCHAR(200) NOT NULL,
    UNIQUE (company_id, label)
);
