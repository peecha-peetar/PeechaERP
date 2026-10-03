-- طبقِ درخواستِ صریحِ کاربر («روالِ پخشِ سرد: سفارشِ تصویب‌شده باید برود
-- قسمتِ انبار و توزین [اگر داشته باشد]؛ بعدِ تاییدِ هردو، تبدیل به
-- فاکتورِ فروش شود؛ بعد فاکتورهایِ تاییدشده توسطِ واحدِ پخش به خودرو و
-- راننده الصاق شوند و در فرمِ «تیمِ پخش»، ریزِ اقلام و جمعِ هر کالا به
-- راننده تحویل داده شود»): این مهاجرت دو بخش دارد --
--
-- ۱) دو گیتِ تاییدِ اضافی رویِ خودِ سفارش (فقط برایِ سفارش‌هایِ کانالِ
--    PRE_SALES معنا دارند؛ در سرویس چک می‌شود، نه با CHECK constraint --
--    چون همان یک ستونِ عمومیِ commercial_documents برایِ همه‌یِ کانال‌ها و
--    انواعِ سند استفاده می‌شود): تاییدِ انبار، و تاییدِ توزین (فقط وقتی
--    حداقل یک ردیفِ سفارش، کالایی با pos_requires_weight=true دارد --
--    همان فیلدِ ازپیش‌موجودِ «این کالا با ترازو وزن می‌شود»، که برایِ
--    توزینِ بارگیری هم دقیقاً همان معنایِ فیزیکی را دارد؛ فیلدِ جدیدِ
--    جداگانه نساختیم).
--
-- ۲) دو جدولِ تازه برایِ «تیمِ پخش»: هر تیم یک خودرو (انبارِ نوعِ VEHICLE
--    که از پیش راننده/پلاکش رویِ خودش دارد) + تاریخ است؛ فاکتورهایِ
--    فروشِ ثبت‌نهایی‌شده‌یِ کانالِ PRE_SALES/VAN_SALES به آن الصاق
--    می‌شوند (comm.distribution_run_documents).

ALTER TABLE comm.commercial_documents
    ADD COLUMN warehouse_approved_by_user_id INT REFERENCES sec.users(user_id),
    ADD COLUMN warehouse_approved_at TIMESTAMPTZ,
    ADD COLUMN weighing_approved_by_user_id INT REFERENCES sec.users(user_id),
    ADD COLUMN weighing_approved_at TIMESTAMPTZ;

CREATE TABLE comm.distribution_runs (
    distribution_run_id BIGSERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES core.companies(company_id),
    run_date DATE NOT NULL,
    vehicle_warehouse_id INT NOT NULL REFERENCES inv.warehouses(warehouse_id),
    status_code VARCHAR(15) NOT NULL DEFAULT 'DRAFT',
    notes TEXT,
    created_by_user_id INT NOT NULL REFERENCES sec.users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_by_user_id INT REFERENCES sec.users(user_id),
    confirmed_at TIMESTAMPTZ
);

CREATE TABLE comm.distribution_run_documents (
    distribution_run_id BIGINT NOT NULL REFERENCES comm.distribution_runs(distribution_run_id),
    document_id BIGINT NOT NULL REFERENCES comm.commercial_documents(document_id),
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (distribution_run_id, document_id)
);

-- طبقِ رفعِ ابهامِ احتمالی: یک فاکتور نباید هم‌زمان در دو تیمِ پخشِ غیرِ
-- کنسل‌شده حضور داشته باشد -- این با ایندکسِ زیر تضمین نمی‌شود (چون
-- وضعیتِ run در جدولِ دیگری است)، پس در لایهٔ سرویس چک می‌شود؛ این
-- ایندکس فقط برایِ سرعتِ کوئریِ «این فاکتور در کدام تیم(ها) است؟».
CREATE INDEX idx_distribution_run_documents_document_id ON comm.distribution_run_documents(document_id);
