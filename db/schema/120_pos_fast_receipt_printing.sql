-- طبقِ رفعِ باگِ واقعی («دکمهٔ تسویه با پرینت خیلی طول می‌کشد»): سویچِ
-- «چاپِ سریعِ فیش» -- پیش‌فرض روشن، یعنی مسیرِ HTMLِ سریع (بدونِ بالا
-- آمدنِ JVMِ Jasper در هر فروش) استفاده شود.
ALTER TABLE comm.pos_settings
    ADD COLUMN fast_receipt_printing BOOLEAN NOT NULL DEFAULT TRUE;
