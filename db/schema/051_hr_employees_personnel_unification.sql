-- پیچا | یکپارچه‌سازیِ «تعریفِ کارمند فقط از طریقِ تفصیلی»: از این پس
-- hr.employees.personnel_detail_account_id همیشه پر و یکتاست — صفحه‌یِ
-- مستقلِ قدیمیِ «تعریفِ کارکنان» حذف شده و detail_dimensions.py تنها
-- نقطه‌یِ تعریف/ویرایشِ کارمند است.

-- بک‌فیل: هر کارمندِ ازپیش‌موجود که هنوز به تفصیلی وصل نیست (چون از
-- طریقِ فرمِ قدیمیِ HR ساخته شده و ساختِ خودکارِ تفصیلی‌اش شکست خورده
-- بوده، طبقِ همان except Exception: personnel_detail_account_id = None
-- در create_employee)، یک تفصیلیِ گروهِ PERSONNEل متناظر می‌گیرد.
DO $$
DECLARE
    emp RECORD;
    v_dimension_type_id SMALLINT;
    v_person_group_id INT;
    v_detail_account_id INT;
    v_code TEXT;
    v_suffix INT;
BEGIN
    FOR emp IN SELECT * FROM hr.employees WHERE personnel_detail_account_id IS NULL LOOP
        SELECT dimension_type_id INTO v_dimension_type_id
        FROM acc.detail_dimension_types WHERE company_id = emp.company_id AND code = 'PERSON';

        SELECT person_group_id INTO v_person_group_id
        FROM acc.person_groups WHERE company_id = emp.company_id AND code = 'PERSONNEL';
        IF v_person_group_id IS NULL THEN
            INSERT INTO acc.person_groups (company_id, code, name, is_active, is_personnel)
            VALUES (emp.company_id, 'PERSONNEL', 'پرسنل', TRUE, TRUE)
            RETURNING person_group_id INTO v_person_group_id;
        END IF;

        v_code := emp.employee_code;
        v_suffix := 1;
        LOOP
            BEGIN
                INSERT INTO acc.detail_accounts
                    (company_id, dimension_type_id, person_group_id, code, name, level_no, is_active, extra_fields)
                VALUES (
                    emp.company_id, v_dimension_type_id, v_person_group_id, v_code,
                    NULLIF(trim(emp.first_name || ' ' || emp.last_name), ''), 1,
                    (emp.status <> 'TERMINATED'), '{}'::jsonb
                )
                RETURNING detail_account_id INTO v_detail_account_id;
                EXIT;
            EXCEPTION WHEN unique_violation THEN
                v_suffix := v_suffix + 1;
                v_code := emp.employee_code || '-' || v_suffix;
            END;
        END LOOP;

        INSERT INTO acc.personnel_details
            (detail_account_id, national_id, personnel_no, phone, mobile, hire_date, bank_account_no, notes)
        VALUES (v_detail_account_id, emp.national_id, v_code, emp.phone, emp.mobile, emp.hire_date, emp.bank_account_no, emp.notes);

        UPDATE hr.employees SET personnel_detail_account_id = v_detail_account_id WHERE employee_id = emp.employee_id;
    END LOOP;
END $$;

ALTER TABLE hr.employees ALTER COLUMN personnel_detail_account_id SET NOT NULL;
ALTER TABLE hr.employees ADD CONSTRAINT uq_hr_employees_personnel_detail_account UNIQUE (personnel_detail_account_id);
