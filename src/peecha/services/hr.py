"""سرویسِ هستهٔ منابع انسانی (hr.*) — فازِ ۱ از ماژولِ حقوق و دستمزد.

طبقِ سندِ طراحی: personnel_detail_account_id هر کارمند به‌طورِ خودکار در
گروهِ شخصیِ PERSONNEL موجود (detail_dimensions.create_personnel) ساخته
می‌شود تا کارمند در اسنادِ حسابداری/خزانه‌داری به‌عنوانِ تفصیلی قابلِ‌انتخاب
باشد — بدونِ بازسازیِ زیرساختِ تفصیلی‌هایِ موجود."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.hr import (
    Employee,
    EmploymentContract,
    JobGrade,
    LookupType,
    LookupValue,
    OrganizationalUnit,
    Position,
    Termination,
)
from peecha.services import detail_dimensions as dimensions_service


# ---------------------------------------------------------------------
# Lookup عمومی
# ---------------------------------------------------------------------
@dataclass
class LookupValueRow:
    lookup_value_id: int
    code: str
    name: str
    is_active: bool


def list_lookup_values(company_id: int, type_code: str, active_only: bool = True) -> list[LookupValueRow]:
    with new_session() as session:
        lookup_type = session.scalar(select(LookupType).where(LookupType.code == type_code))
        if lookup_type is None:
            return []
        query = select(LookupValue).where(
            LookupValue.lookup_type_id == lookup_type.lookup_type_id,
            (LookupValue.company_id == company_id) | (LookupValue.company_id.is_(None)),
        )
        if active_only:
            query = query.where(LookupValue.is_active)
        rows = session.scalars(query.order_by(LookupValue.display_order)).all()
        return [LookupValueRow(r.lookup_value_id, r.code, r.name, r.is_active) for r in rows]


# ---------------------------------------------------------------------
# واحدهایِ سازمانی
# ---------------------------------------------------------------------
@dataclass
class OrgUnitRow:
    org_unit_id: int
    code: str
    name: str
    parent_org_unit_id: int | None
    parent_name: str | None
    cost_center_detail_account_id: int | None
    is_active: bool


def list_org_units(company_id: int) -> list[OrgUnitRow]:
    with new_session() as session:
        units = session.scalars(
            select(OrganizationalUnit).where(OrganizationalUnit.company_id == company_id).order_by(OrganizationalUnit.code)
        ).all()
        names = {u.org_unit_id: u.name for u in units}
        return [
            OrgUnitRow(
                org_unit_id=u.org_unit_id,
                code=u.code,
                name=u.name,
                parent_org_unit_id=u.parent_org_unit_id,
                parent_name=names.get(u.parent_org_unit_id) if u.parent_org_unit_id else None,
                cost_center_detail_account_id=u.cost_center_detail_account_id,
                is_active=u.is_active,
            )
            for u in units
        ]


def create_org_unit(
    company_id: int,
    code: str,
    name: str,
    parent_org_unit_id: int | None,
    cost_center_detail_account_id: int | None,
) -> int:
    code = code.strip()
    name = name.strip()
    if not code or not name:
        raise ValueError("کد و نام الزامی است.")
    with new_session() as session:
        exists = session.scalar(
            select(OrganizationalUnit).where(OrganizationalUnit.company_id == company_id, OrganizationalUnit.code == code)
        )
        if exists is not None:
            raise ValueError("این کد قبلاً استفاده شده است.")
        unit = OrganizationalUnit(
            company_id=company_id,
            code=code,
            name=name,
            parent_org_unit_id=parent_org_unit_id,
            cost_center_detail_account_id=cost_center_detail_account_id,
        )
        session.add(unit)
        session.commit()
        return unit.org_unit_id


def update_org_unit(
    org_unit_id: int,
    name: str,
    parent_org_unit_id: int | None,
    cost_center_detail_account_id: int | None,
    is_active: bool,
) -> None:
    name = name.strip()
    if not name:
        raise ValueError("نام الزامی است.")
    if parent_org_unit_id == org_unit_id:
        raise ValueError("یک واحد نمی‌تواند والدِ خودش باشد.")
    with new_session() as session:
        unit = session.get(OrganizationalUnit, org_unit_id)
        if unit is None:
            raise ValueError("واحدِ سازمانی یافت نشد.")
        unit.name = name
        unit.parent_org_unit_id = parent_org_unit_id
        unit.cost_center_detail_account_id = cost_center_detail_account_id
        unit.is_active = is_active
        session.commit()


def delete_org_unit(org_unit_id: int) -> None:
    with new_session() as session:
        unit = session.get(OrganizationalUnit, org_unit_id)
        if unit is None:
            return
        in_use = session.scalar(select(Position).where(Position.org_unit_id == org_unit_id))
        has_children = session.scalar(select(OrganizationalUnit).where(OrganizationalUnit.parent_org_unit_id == org_unit_id))
        if in_use is not None or has_children is not None:
            raise ValueError("این واحد دارایِ پست یا زیرمجموعه است و قابلِ حذف نیست.")
        session.delete(unit)
        session.commit()


# ---------------------------------------------------------------------
# رده‌هایِ شغلی
# ---------------------------------------------------------------------
@dataclass
class JobGradeRow:
    job_grade_id: int
    code: str
    title: str
    grade_level: int
    min_base_salary: decimal.Decimal | None
    max_base_salary: decimal.Decimal | None
    is_active: bool


def list_job_grades(company_id: int) -> list[JobGradeRow]:
    with new_session() as session:
        rows = session.scalars(
            select(JobGrade).where(JobGrade.company_id == company_id).order_by(JobGrade.grade_level)
        ).all()
        return [
            JobGradeRow(r.job_grade_id, r.code, r.title, r.grade_level, r.min_base_salary, r.max_base_salary, r.is_active)
            for r in rows
        ]


def create_job_grade(
    company_id: int,
    code: str,
    title: str,
    grade_level: int,
    min_base_salary: decimal.Decimal | None,
    max_base_salary: decimal.Decimal | None,
) -> int:
    code = code.strip()
    title = title.strip()
    if not code or not title:
        raise ValueError("کد و عنوان الزامی است.")
    if min_base_salary is not None and max_base_salary is not None and min_base_salary > max_base_salary:
        raise ValueError("حداقلِ حقوق نمی‌تواند بیشتر از حداکثر باشد.")
    with new_session() as session:
        exists = session.scalar(select(JobGrade).where(JobGrade.company_id == company_id, JobGrade.code == code))
        if exists is not None:
            raise ValueError("این کد قبلاً استفاده شده است.")
        grade = JobGrade(
            company_id=company_id,
            code=code,
            title=title,
            grade_level=grade_level,
            min_base_salary=min_base_salary,
            max_base_salary=max_base_salary,
        )
        session.add(grade)
        session.commit()
        return grade.job_grade_id


def update_job_grade(
    job_grade_id: int,
    title: str,
    grade_level: int,
    min_base_salary: decimal.Decimal | None,
    max_base_salary: decimal.Decimal | None,
    is_active: bool,
) -> None:
    title = title.strip()
    if not title:
        raise ValueError("عنوان الزامی است.")
    if min_base_salary is not None and max_base_salary is not None and min_base_salary > max_base_salary:
        raise ValueError("حداقلِ حقوق نمی‌تواند بیشتر از حداکثر باشد.")
    with new_session() as session:
        grade = session.get(JobGrade, job_grade_id)
        if grade is None:
            raise ValueError("ردهٔ شغلی یافت نشد.")
        grade.title = title
        grade.grade_level = grade_level
        grade.min_base_salary = min_base_salary
        grade.max_base_salary = max_base_salary
        grade.is_active = is_active
        session.commit()


def delete_job_grade(job_grade_id: int) -> None:
    with new_session() as session:
        grade = session.get(JobGrade, job_grade_id)
        if grade is None:
            return
        in_use = session.scalar(select(Position).where(Position.job_grade_id == job_grade_id))
        if in_use is not None:
            raise ValueError("این رده برایِ یک یا چند پست استفاده شده و قابلِ حذف نیست.")
        session.delete(grade)
        session.commit()


# ---------------------------------------------------------------------
# پست‌هایِ سازمانی
# ---------------------------------------------------------------------
@dataclass
class PositionRow:
    position_id: int
    code: str
    title: str
    org_unit_id: int
    org_unit_name: str
    job_grade_id: int | None
    job_grade_title: str | None
    capacity: int
    is_active: bool


def list_positions(company_id: int) -> list[PositionRow]:
    with new_session() as session:
        rows = session.scalars(select(Position).where(Position.company_id == company_id).order_by(Position.code)).all()
        org_units = {u.org_unit_id: u.name for u in session.scalars(select(OrganizationalUnit))}
        grades = {g.job_grade_id: g.title for g in session.scalars(select(JobGrade))}
        return [
            PositionRow(
                position_id=r.position_id,
                code=r.code,
                title=r.title,
                org_unit_id=r.org_unit_id,
                org_unit_name=org_units.get(r.org_unit_id, "?"),
                job_grade_id=r.job_grade_id,
                job_grade_title=grades.get(r.job_grade_id) if r.job_grade_id else None,
                capacity=r.capacity,
                is_active=r.is_active,
            )
            for r in rows
        ]


def create_position(
    company_id: int,
    code: str,
    title: str,
    org_unit_id: int,
    job_grade_id: int | None,
    capacity: int,
) -> int:
    code = code.strip()
    title = title.strip()
    if not code or not title:
        raise ValueError("کد و عنوان الزامی است.")
    if capacity < 1:
        raise ValueError("ظرفیت باید حداقل ۱ باشد.")
    with new_session() as session:
        exists = session.scalar(select(Position).where(Position.company_id == company_id, Position.code == code))
        if exists is not None:
            raise ValueError("این کد قبلاً استفاده شده است.")
        position = Position(
            company_id=company_id,
            code=code,
            title=title,
            org_unit_id=org_unit_id,
            job_grade_id=job_grade_id,
            capacity=capacity,
        )
        session.add(position)
        session.commit()
        return position.position_id


def update_position(
    position_id: int,
    title: str,
    org_unit_id: int,
    job_grade_id: int | None,
    capacity: int,
    is_active: bool,
) -> None:
    title = title.strip()
    if not title:
        raise ValueError("عنوان الزامی است.")
    if capacity < 1:
        raise ValueError("ظرفیت باید حداقل ۱ باشد.")
    with new_session() as session:
        position = session.get(Position, position_id)
        if position is None:
            raise ValueError("پست یافت نشد.")
        position.title = title
        position.org_unit_id = org_unit_id
        position.job_grade_id = job_grade_id
        position.capacity = capacity
        position.is_active = is_active
        session.commit()


def delete_position(position_id: int) -> None:
    with new_session() as session:
        position = session.get(Position, position_id)
        if position is None:
            return
        in_use = session.scalar(select(EmploymentContract).where(EmploymentContract.position_id == position_id))
        if in_use is not None:
            raise ValueError("این پست دارایِ قرارداد است و قابلِ حذف نیست.")
        session.delete(position)
        session.commit()


# ---------------------------------------------------------------------
# کارمندان + قراردادِ فعال (نمایِ ترکیبی برایِ فهرست/فرم)
# ---------------------------------------------------------------------
@dataclass
class EmployeeRow:
    employee_id: int
    employee_code: str
    full_name: str
    national_id: str | None
    hire_date: datetime.date
    status: str
    active_contract_id: int | None
    org_unit_name: str | None
    position_title: str | None
    base_salary: decimal.Decimal | None


def list_employees(company_id: int) -> list[EmployeeRow]:
    with new_session() as session:
        employees = session.scalars(select(Employee).where(Employee.company_id == company_id).order_by(Employee.employee_code)).all()
        contracts = {
            c.employee_id: c
            for c in session.scalars(select(EmploymentContract).where(EmploymentContract.status == "ACTIVE"))
        }
        org_units = {u.org_unit_id: u.name for u in session.scalars(select(OrganizationalUnit))}
        positions = {p.position_id: p.title for p in session.scalars(select(Position))}
        rows = []
        for e in employees:
            contract = contracts.get(e.employee_id)
            rows.append(
                EmployeeRow(
                    employee_id=e.employee_id,
                    employee_code=e.employee_code,
                    full_name=f"{e.first_name} {e.last_name}".strip(),
                    national_id=e.national_id,
                    hire_date=e.hire_date,
                    status=e.status,
                    active_contract_id=contract.contract_id if contract else None,
                    org_unit_name=org_units.get(contract.org_unit_id) if contract else None,
                    position_title=positions.get(contract.position_id) if contract else None,
                    base_salary=contract.base_salary if contract else None,
                )
            )
        return rows


@dataclass
class EmployeeDetail:
    employee_id: int
    employee_code: str
    first_name: str
    last_name: str
    national_id: str | None
    date_of_birth: datetime.date | None
    hire_date: datetime.date
    social_security_no: str | None
    bank_account_no: str | None
    bank_iban: str | None
    phone: str | None
    mobile: str | None
    address: str | None
    status: str
    notes: str | None
    active_contract_id: int | None
    org_unit_id: int | None
    position_id: int | None
    base_salary: decimal.Decimal | None
    employment_type_lookup_id: int | None
    personnel_detail_account_id: int | None


def get_employee(employee_id: int) -> EmployeeDetail | None:
    with new_session() as session:
        e = session.get(Employee, employee_id)
        if e is None:
            return None
        contract = session.scalar(
            select(EmploymentContract).where(EmploymentContract.employee_id == employee_id, EmploymentContract.status == "ACTIVE")
        )
        return EmployeeDetail(
            employee_id=e.employee_id,
            employee_code=e.employee_code,
            first_name=e.first_name,
            last_name=e.last_name,
            national_id=e.national_id,
            date_of_birth=e.date_of_birth,
            hire_date=e.hire_date,
            social_security_no=e.social_security_no,
            bank_account_no=e.bank_account_no,
            bank_iban=e.bank_iban,
            phone=e.phone,
            mobile=e.mobile,
            address=e.address,
            status=e.status,
            notes=e.notes,
            active_contract_id=contract.contract_id if contract else None,
            org_unit_id=contract.org_unit_id if contract else None,
            position_id=contract.position_id if contract else None,
            base_salary=contract.base_salary if contract else None,
            employment_type_lookup_id=contract.employment_type_lookup_id if contract else None,
            personnel_detail_account_id=e.personnel_detail_account_id,
        )


def create_employee(
    company_id: int,
    employee_code: str,
    first_name: str,
    last_name: str,
    national_id: str | None,
    hire_date: datetime.date,
    org_unit_id: int,
    position_id: int,
    base_salary: decimal.Decimal,
    employment_type_lookup_id: int | None,
    *,
    date_of_birth: datetime.date | None = None,
    social_security_no: str | None = None,
    bank_account_no: str | None = None,
    bank_iban: str | None = None,
    phone: str | None = None,
    mobile: str | None = None,
    address: str | None = None,
    notes: str | None = None,
    existing_personnel_detail_account_id: int | None = None,
) -> int:
    """اگر existing_personnel_detail_account_id داده شود (طبقِ خواسته‌یِ
    صریح: «تفصیلیِ کارکنانی که قبلاً دستی تعریف کرده بودم باید به همین
    کارمندِ تازه وصل شود، نه اینکه یک تفصیلیِ تکراری ساخته شود»)، همان
    تفصیلیِ ازپیش‌موجود استفاده و بلافاصله با اطلاعاتِ همین فرم به‌روزرسانی
    می‌شود؛ در غیرِ این صورت (کارمندِ کاملاً تازه، بدونِ تفصیلیِ قبلی)،
    طبقِ رفتارِ قبلی یک تفصیلیِ تازه در گروهِ PERSONNEL ساخته می‌شود."""
    employee_code = employee_code.strip()
    first_name = first_name.strip()
    last_name = last_name.strip()
    if not employee_code or not first_name:
        raise ValueError("کدِ پرسنلی و نام الزامی است.")
    if base_salary <= 0:
        raise ValueError("حقوقِ پایه باید مثبت باشد.")

    with new_session() as session:
        exists = session.scalar(select(Employee).where(Employee.company_id == company_id, Employee.employee_code == employee_code))
        if exists is not None:
            raise ValueError("این کدِ پرسنلی قبلاً استفاده شده است.")

        if existing_personnel_detail_account_id is not None:
            already_linked = session.scalar(
                select(Employee).where(Employee.personnel_detail_account_id == existing_personnel_detail_account_id)
            )
            if already_linked is not None:
                raise ValueError("این تفصیلیِ حسابداری قبلاً به کارمندِ دیگری وصل شده است.")
            personnel_detail_account_id = existing_personnel_detail_account_id
            existing_code = next(
                (p["code"] for p in dimensions_service.list_personnel(company_id) if p["detail_account_id"] == existing_personnel_detail_account_id),
                employee_code,
            )
            try:
                dimensions_service.update_personnel(
                    existing_personnel_detail_account_id,
                    company_id,
                    existing_code,
                    f"{first_name} {last_name}".strip(),
                    True,
                    national_id=national_id,
                    phone=phone,
                    mobile=mobile,
                    bank_account_no=bank_account_no,
                    notes=notes,
                )
            except ValueError:
                pass
        else:
            # طبقِ سندِ طراحی: تفصیلیِ حسابداریِ گروهِ PERSONNEL موجود به‌طورِ
            # خودکار برایِ این کارمند ساخته می‌شود تا در اسنادِ حسابداری/خزانه‌داری
            # قابلِ‌انتخاب باشد.
            try:
                personnel_detail_account_id = dimensions_service.create_personnel(
                    company_id,
                    employee_code,
                    f"{first_name} {last_name}".strip(),
                    national_id=national_id,
                    personnel_no=employee_code,
                    hire_date=hire_date,
                    bank_account_no=bank_account_no,
                )
            except Exception:
                personnel_detail_account_id = None

        employee = Employee(
            company_id=company_id,
            personnel_detail_account_id=personnel_detail_account_id,
            employee_code=employee_code,
            first_name=first_name,
            last_name=last_name,
            national_id=national_id,
            date_of_birth=date_of_birth,
            hire_date=hire_date,
            social_security_no=social_security_no,
            bank_account_no=bank_account_no,
            bank_iban=bank_iban,
            phone=phone,
            mobile=mobile,
            address=address,
            notes=notes,
        )
        session.add(employee)
        session.flush()

        contract = EmploymentContract(
            employee_id=employee.employee_id,
            employment_type_lookup_id=employment_type_lookup_id,
            org_unit_id=org_unit_id,
            position_id=position_id,
            start_date=hire_date,
            base_salary=base_salary,
            status="ACTIVE",
        )
        session.add(contract)
        session.commit()
        return employee.employee_id


def update_employee(
    employee_id: int,
    first_name: str,
    last_name: str,
    national_id: str | None,
    status: str,
    *,
    date_of_birth: datetime.date | None = None,
    social_security_no: str | None = None,
    bank_account_no: str | None = None,
    bank_iban: str | None = None,
    phone: str | None = None,
    mobile: str | None = None,
    address: str | None = None,
    notes: str | None = None,
) -> None:
    first_name = first_name.strip()
    last_name = last_name.strip()
    if not first_name:
        raise ValueError("نام الزامی است.")
    if status not in ("ACTIVE", "ON_LEAVE", "TERMINATED"):
        raise ValueError("وضعیتِ نامعتبر.")
    with new_session() as session:
        employee = session.get(Employee, employee_id)
        if employee is None:
            raise ValueError("کارمند یافت نشد.")
        employee.first_name = first_name
        employee.last_name = last_name
        employee.national_id = national_id
        employee.status = status
        employee.date_of_birth = date_of_birth
        employee.social_security_no = social_security_no
        employee.bank_account_no = bank_account_no
        employee.bank_iban = bank_iban
        employee.phone = phone
        employee.mobile = mobile
        employee.address = address
        employee.notes = notes
        session.commit()


def update_active_contract(
    contract_id: int,
    org_unit_id: int,
    position_id: int,
    base_salary: decimal.Decimal,
    employment_type_lookup_id: int | None,
) -> None:
    """جابه‌جاییِ سازمانی/تغییرِ حقوق روی همان قراردادِ فعال — نسخه‌بندیِ
    کاملِ تاریخچهٔ قرارداد (چندین ردیف) در فازِ بعدی افزوده می‌شود؛ فعلاً
    برایِ سادگیِ فازِ ۱، تغییرات مستقیماً رویِ قراردادِ فعال اعمال می‌شوند."""
    if base_salary <= 0:
        raise ValueError("حقوقِ پایه باید مثبت باشد.")
    with new_session() as session:
        contract = session.get(EmploymentContract, contract_id)
        if contract is None or contract.status != "ACTIVE":
            raise ValueError("قراردادِ فعال یافت نشد.")
        contract.org_unit_id = org_unit_id
        contract.position_id = position_id
        contract.base_salary = base_salary
        contract.employment_type_lookup_id = employment_type_lookup_id
        session.commit()


def terminate_employee(
    employee_id: int,
    termination_date: datetime.date,
    termination_type_lookup_id: int | None,
    reason: str | None,
) -> None:
    with new_session() as session:
        employee = session.get(Employee, employee_id)
        if employee is None:
            raise ValueError("کارمند یافت نشد.")
        contract = session.scalar(
            select(EmploymentContract).where(EmploymentContract.employee_id == employee_id, EmploymentContract.status == "ACTIVE")
        )
        if contract is None:
            raise ValueError("این کارمند قراردادِ فعالی ندارد.")
        if termination_date < contract.start_date:
            raise ValueError("تاریخِ پایانِ همکاری نمی‌تواند قبل از تاریخِ شروعِ قرارداد باشد.")

        contract.status = "ENDED"
        contract.end_date = termination_date
        contract.end_reason_lookup_id = termination_type_lookup_id
        employee.status = "TERMINATED"
        session.add(
            Termination(
                employee_id=employee_id,
                contract_id=contract.contract_id,
                termination_date=termination_date,
                termination_type_lookup_id=termination_type_lookup_id,
                reason=reason,
            )
        )
        session.commit()

        # طبقِ یکپارچگیِ تعریف‌شده: تفصیلیِ حسابداریِ کارمندِ پایان‌یافته
        # باید غیرِفعال شود تا در انتخاب‌گرهایِ سندِ حسابداری/خزانه‌داری
        # دیگر به‌عنوانِ گزینهٔ فعال ظاهر نشود (خودِ سوابقِ قبلی دست‌نخورده
        # می‌مانند، چون غیرِفعال‌سازی است نه حذف).
        if employee.personnel_detail_account_id is not None:
            try:
                dimensions_service.update_personnel(
                    employee.personnel_detail_account_id,
                    employee.company_id,
                    employee.employee_code,
                    f"{employee.first_name} {employee.last_name}".strip(),
                    False,
                )
            except ValueError:
                pass


_PERSONNEL_HR_FIELD_KEYS = ("org_unit_id", "position_id", "employment_type_lookup_id", "base_salary")


def _split_personnel_fields(person_fields: dict) -> tuple[dict, dict]:
    """جداکردنِ فیلدهایِ سطحِ HR (قراردادِ استخدام) از فیلدهایِ سطحِ
    PersonnelDetail که فرمِ واحدِ تفصیلی (detail_dimensions.py) با هم
    می‌فرستد، چون این دو دسته به دو تابعِ سرویسِ متفاوت می‌روند."""
    hr_fields = {k: person_fields.get(k) for k in _PERSONNEL_HR_FIELD_KEYS}
    detail_fields = {k: v for k, v in person_fields.items() if k not in _PERSONNEL_HR_FIELD_KEYS}
    return detail_fields, hr_fields


def _personnel_group_max_level_no(company_id: int) -> int:
    dimension_type_id = dimensions_service.get_person_dimension_type_id(company_id)
    person_group_id = dimensions_service.get_person_group_id(company_id, dimensions_service.PERSONNEL_GROUP_CODE)
    return dimensions_service.get_group_max_level_no(dimension_type_id, person_group_id)


def _is_personnel_leaf_level(company_id: int, level_no: int) -> bool:
    """طبقِ گزارشِ صریح: وقتی گروهِ پرسنل چند سطح دارد (مثلاً واحد/زیرمجموعه
    → کارمند)، فقط آخرین سطح یک «کارمندِ واقعی» است — سطوحِ بالاتر صرفاً
    گره‌هایِ گروه‌بندی‌اند و نباید شغل/سازمان/رده‌یِ شغلی/حقوقِ پایه (که
    فقط برایِ قراردادِ واقعیِ استخدام معنا دارند) از آن‌ها پرسیده شود یا
    ردیفِ hr.employees برایشان ساخته شود."""
    return level_no >= _personnel_group_max_level_no(company_id)


def get_employee_by_personnel_detail_account_id(personnel_detail_account_id: int) -> EmployeeDetail | None:
    with new_session() as session:
        employee = session.scalar(
            select(Employee).where(Employee.personnel_detail_account_id == personnel_detail_account_id)
        )
        if employee is None:
            return None
        employee_id = employee.employee_id
    return get_employee(employee_id)


def list_personnel_detail_accounts(company_id: int) -> list[dict]:
    """جایگزینِ dimensions_service.list_personnel در _PERSON_GROUP_META
    (detail_dimensions.py) — همان ردیف‌هایِ تفصیلیِ گروهِ PERSONNEL را با
    اطلاعاتِ قراردادِ فعال (واحدِ سازمانی/پست/حقوقِ پایه/نوعِ استخدام) و
    وضعیتِ استخدامِ کارمندِ متناظر تلفیق می‌کند، تا فرمِ تفصیلی دیگر نیازی
    به فرمِ جداگانه‌یِ «تعریفِ کارکنان» نداشته باشد."""
    with new_session() as session:
        employees = session.scalars(select(Employee).where(Employee.company_id == company_id)).all()
        contracts = {
            c.employee_id: c
            for c in session.scalars(select(EmploymentContract).where(EmploymentContract.status == "ACTIVE"))
        }
        org_units = {u.org_unit_id: u.name for u in session.scalars(select(OrganizationalUnit))}
        positions = {p.position_id: p.title for p in session.scalars(select(Position))}
        by_detail_account_id: dict[int, dict] = {}
        for e in employees:
            if e.personnel_detail_account_id is None:
                continue
            contract = contracts.get(e.employee_id)
            by_detail_account_id[e.personnel_detail_account_id] = {
                "employee_id": e.employee_id,
                "employee_status": e.status,
                "org_unit_id": contract.org_unit_id if contract else None,
                "org_unit_name": org_units.get(contract.org_unit_id) if contract else None,
                "position_id": contract.position_id if contract else None,
                "position_name": positions.get(contract.position_id) if contract else None,
                "employment_type_lookup_id": contract.employment_type_lookup_id if contract else None,
                "base_salary": contract.base_salary if contract else None,
            }

    _blank = {
        "employee_id": None, "employee_status": None, "org_unit_id": None, "org_unit_name": None,
        "position_id": None, "position_name": None, "employment_type_lookup_id": None, "base_salary": None,
    }
    result = []
    for p in dimensions_service.list_personnel(company_id):
        merged = dict(p)
        merged.update(by_detail_account_id.get(p["detail_account_id"], _blank))
        result.append(merged)
    return result


def create_personnel_detail_account(
    company_id: int,
    code: str,
    name: str,
    custom_fields: dict | None = None,
    parent_detail_account_id: int | None = None,
    **person_fields,
) -> int:
    detail_fields, hr_fields = _split_personnel_fields(person_fields)
    level_no = 1
    if parent_detail_account_id is not None:
        parent_level_no = dimensions_service.get_detail_account_level_no(parent_detail_account_id)
        level_no = (parent_level_no or 0) + 1
    is_leaf_level = _is_personnel_leaf_level(company_id, level_no)

    if is_leaf_level:
        if hr_fields["org_unit_id"] is None or hr_fields["position_id"] is None:
            raise ValueError("واحدِ سازمانی و پست را انتخاب کنید.")
        if not hr_fields["base_salary"] or hr_fields["base_salary"] <= 0:
            raise ValueError("حقوقِ پایه باید مثبت باشد.")

    detail_account_id = dimensions_service.create_personnel(
        company_id, code, name, custom_fields=custom_fields,
        parent_detail_account_id=parent_detail_account_id, personnel_no=code, **detail_fields,
    )
    if is_leaf_level:
        create_employee(
            company_id, code, name.strip() or code, "", detail_fields.get("national_id"),
            detail_fields.get("hire_date") or datetime.date.today(),
            hr_fields["org_unit_id"], hr_fields["position_id"], hr_fields["base_salary"],
            hr_fields["employment_type_lookup_id"],
            bank_account_no=detail_fields.get("bank_account_no"), phone=detail_fields.get("phone"),
            mobile=detail_fields.get("mobile"), notes=detail_fields.get("notes"),
            existing_personnel_detail_account_id=detail_account_id,
        )
    return detail_account_id


def update_personnel_detail_account(
    detail_account_id: int,
    company_id: int,
    code: str,
    name: str,
    is_active: bool,
    custom_fields: dict | None = None,
    **person_fields,
) -> None:
    detail_fields, hr_fields = _split_personnel_fields(person_fields)
    level_no = dimensions_service.get_detail_account_level_no(detail_account_id) or 1
    is_leaf_level = _is_personnel_leaf_level(company_id, level_no)

    if is_leaf_level:
        if hr_fields["org_unit_id"] is None or hr_fields["position_id"] is None:
            raise ValueError("واحدِ سازمانی و پست را انتخاب کنید.")
        if not hr_fields["base_salary"] or hr_fields["base_salary"] <= 0:
            raise ValueError("حقوقِ پایه باید مثبت باشد.")

    dimensions_service.update_personnel(
        detail_account_id, company_id, code, name, is_active,
        custom_fields=custom_fields, personnel_no=code, **detail_fields,
    )

    if not is_leaf_level:
        return

    employee = get_employee_by_personnel_detail_account_id(detail_account_id)
    if employee is None:
        # خودترمیمی: تفصیلیِ پرسنلِ یتیمِ ازپیش‌موجود (پیش از این یکپارچه‌سازی)
        create_employee(
            company_id, code, name.strip() or code, "", detail_fields.get("national_id"),
            detail_fields.get("hire_date") or datetime.date.today(),
            hr_fields["org_unit_id"], hr_fields["position_id"], hr_fields["base_salary"],
            hr_fields["employment_type_lookup_id"],
            bank_account_no=detail_fields.get("bank_account_no"), phone=detail_fields.get("phone"),
            mobile=detail_fields.get("mobile"), notes=detail_fields.get("notes"),
            existing_personnel_detail_account_id=detail_account_id,
        )
        return

    update_employee(
        employee.employee_id, name.strip() or code, "", detail_fields.get("national_id"), employee.status,
        date_of_birth=employee.date_of_birth, social_security_no=employee.social_security_no,
        bank_account_no=detail_fields.get("bank_account_no"), bank_iban=employee.bank_iban,
        phone=detail_fields.get("phone"), mobile=detail_fields.get("mobile"),
        address=employee.address, notes=detail_fields.get("notes"),
    )
    if employee.active_contract_id is not None:
        update_active_contract(
            employee.active_contract_id, hr_fields["org_unit_id"], hr_fields["position_id"],
            hr_fields["base_salary"], hr_fields["employment_type_lookup_id"],
        )


def delete_personnel_detail_account(detail_account_id: int, company_id: int) -> None:
    if get_employee_by_personnel_detail_account_id(detail_account_id) is not None:
        raise ValueError("این تفصیلی به یک کارمند وصل است — به‌جایِ حذف، از «ثبتِ ترکِ کار» استفاده کنید.")
    dimensions_service.delete_personnel(detail_account_id, company_id)
