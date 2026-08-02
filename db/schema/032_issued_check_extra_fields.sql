-- فیلدهایِ تکمیلیِ چکِ صادرشده (پرداختی) — هم‌ارزِ همان فیلدهایِ چکِ
-- دریافتی (029_treasury_banks_and_check_fields.sql)، طبقِ درخواستِ صریح:
-- «اطلاعات و فیلدهای چک دریافتی هم در فرمِ پرداخت باشه» — این‌جا برایِ
-- طرفِ دریافت‌کننده‌یِ چک (نه خودمان، که صادرکننده‌ایم).

ALTER TABLE treasury.issued_checks
    ADD COLUMN check_serial       VARCHAR(30) NULL,
    ADD COLUMN iban                VARCHAR(34) NULL,
    ADD COLUMN payee_account_no    VARCHAR(40) NULL,
    ADD COLUMN payee_national_id   VARCHAR(15) NULL,
    ADD COLUMN payee_phone         VARCHAR(20) NULL,
    ADD COLUMN payee_bank_id       INT         NULL REFERENCES treasury.banks(bank_id);
