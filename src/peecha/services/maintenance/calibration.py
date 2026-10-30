"""R382: کالیبراسیون ابزار اندازه‌گیری.

- هر ابزار (اختیاری متصل به تجهیز/دارایی) دورهٔ کالیبراسیون به روز و چند روز هشدار پیش از سررسید دارد.
- نتیجهٔ «قبول» یا «تنظیم و قبول» سررسید بعدی را از تاریخ همین کالیبراسیون + دوره می‌سازد و ابزار خارج از خدمت را دوباره
  فعال می‌کند. نتیجهٔ «مردود» ابزار را از خدمت خارج می‌کند و سررسید را جابه‌جا نمی‌کند؛ به انتخاب کاربر یک عدم‌انطباق
  کیفیت (علت «اندازه‌گیری») باز می‌شود تا اثر آن بر اندازه‌گیری‌های بعد از آخرین کالیبراسیون قبول بررسی شود.
- ابزار ردشده فقط با کالیبراسیون قبول بعدی به خدمت برمی‌گردد. هزینه فقط برای سابقه است؛ ثبت مالی از فاکتور خرید خدمات است.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import select

from peecha.db.base import new_session
from peecha.db.models.maintenance import CalibrationInstrument, CalibrationRecord
from peecha.services.maintenance import common as c

ENTITY = "MntCalibration"
STATUS_LABELS = {"ACTIVE": "در خدمت", "OUT_OF_SERVICE": "خارج از خدمت", "RETIRED": "بازنشسته"}
RESULT_LABELS = {"PASS": "قبول", "ADJUSTED": "تنظیم و قبول", "FAIL": "مردود"}
METHOD_LABELS = {"EXTERNAL": "آزمایشگاه بیرونی", "INTERNAL": "داخلی"}
STATE_LABELS = {"OK": "در موعد نیست", "DUE": "نزدیک سررسید", "OVERDUE": "گذشته از سررسید", "OUT_OF_SERVICE": "خارج از خدمت",
                "RETIRED": "بازنشسته"}


@dataclass
class InstrumentInput:
    code: str
    name: str
    interval_days: int
    next_due_date: datetime.date
    lead_days: int = 14
    method_code: str = "EXTERNAL"
    asset_id: int | None = None
    serial_no: str | None = None
    location_text: str | None = None
    measure_range: str | None = None
    tolerance: str | None = None
    lab_detail_account_id: int | None = None
    responsible_user_id: int | None = None
    notes: str | None = None


def _clean(value: str | None, size: int) -> str | None:
    return (value or "").strip()[:size] or None


def _validate(d: InstrumentInput) -> None:
    if not (d.code or "").strip() or not (d.name or "").strip():
        raise ValueError("کد و نام ابزار الزامی است.")
    if not d.interval_days or int(d.interval_days) <= 0:
        raise ValueError("دورهٔ کالیبراسیون باید بیشتر از صفر روز باشد.")
    if int(d.lead_days or 0) < 0:
        raise ValueError("روزهای هشدار نمی‌تواند منفی باشد.")
    if d.method_code not in METHOD_LABELS:
        raise ValueError("روش کالیبراسیون نامعتبر است.")
    if d.next_due_date is None:
        raise ValueError("تاریخ سررسید کالیبراسیون را وارد کنید.")


def _get(session, company_id: int, instrument_id: int, lock: bool = False) -> CalibrationInstrument:
    q = select(CalibrationInstrument).where(CalibrationInstrument.instrument_id == instrument_id)
    row = session.scalar(q.with_for_update() if lock else q)
    if row is None or row.company_id != company_id:
        raise ValueError("ابزار اندازه‌گیری نامعتبر است.")
    return row


def save_instrument(company_id: int, user_id: int | None, data: InstrumentInput, instrument_id: int | None = None) -> int:
    """ساخت یا ویرایش؛ در ویرایش، سررسید فقط تا پیش از اولین کالیبراسیون از فرم عوض می‌شود."""
    _validate(data)
    code = data.code.strip().upper()[:30]
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_MANAGE, session=session)
        dup = session.scalar(select(CalibrationInstrument.instrument_id).where(
            CalibrationInstrument.company_id == company_id, CalibrationInstrument.code == code))
        if dup and dup != instrument_id:
            raise ValueError("کد ابزار تکراری است.")
        if data.asset_id is not None:
            c.asset_of(session, company_id, data.asset_id)
        if instrument_id is None:
            row = CalibrationInstrument(company_id=company_id, created_by_user_id=user_id, next_due_date=data.next_due_date)
            session.add(row)
        else:
            row = _get(session, company_id, instrument_id, lock=True)
            if row.last_calibrated_on is None:
                row.next_due_date = data.next_due_date
        row.code, row.name = code, data.name.strip()[:200]
        row.interval_days, row.lead_days, row.method_code = int(data.interval_days), int(data.lead_days or 0), data.method_code
        row.asset_id, row.lab_detail_account_id, row.responsible_user_id = data.asset_id, data.lab_detail_account_id, data.responsible_user_id
        row.serial_no, row.location_text = _clean(data.serial_no, 100), _clean(data.location_text, 200)
        row.measure_range, row.tolerance, row.notes = _clean(data.measure_range, 100), _clean(data.tolerance, 100), _clean(data.notes, 1000)
        session.flush()
        c.audit(session, company_id, user_id, ENTITY, row.instrument_id, "CREATE" if instrument_id is None else "UPDATE",
                {"code": code, "interval_days": row.interval_days})
        session.commit()
        return row.instrument_id


def set_status(company_id: int, user_id: int | None, instrument_id: int, status: str, reason: str = "") -> None:
    if status not in STATUS_LABELS:
        raise ValueError("وضعیت ابزار نامعتبر است.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_MANAGE, session=session)
        row = _get(session, company_id, instrument_id, lock=True)
        if row.status_code == status:
            return
        if status == "ACTIVE":
            last = session.scalar(select(CalibrationRecord.result_code).where(CalibrationRecord.instrument_id == instrument_id)
                                  .order_by(CalibrationRecord.calibrated_on.desc(), CalibrationRecord.record_id.desc()).limit(1))
            if last == "FAIL":
                raise ValueError("ابزار مردود فقط با ثبت کالیبراسیون قبول دوباره به خدمت برمی‌گردد.")
        if status != "ACTIVE" and not (reason or "").strip():
            raise ValueError("دلیل تغییر وضعیت ابزار را بنویسید.")
        old, row.status_code = row.status_code, status
        c.audit(session, company_id, user_id, ENTITY, instrument_id, "UPDATE", {"status": status, "from": old, "reason": (reason or "").strip()})
        session.commit()


def record_calibration(company_id: int, user_id: int | None, instrument_id: int, calibrated_on: datetime.date, result_code: str, *,
                       performed_by: str = "", certificate_no: str = "", as_found: str = "", as_left: str = "", cost_amount=0,
                       notes: str = "", open_ncr: bool = True) -> int:
    if result_code not in RESULT_LABELS:
        raise ValueError("نتیجهٔ کالیبراسیون نامعتبر است.")
    if calibrated_on is None or calibrated_on > datetime.date.today():
        raise ValueError("تاریخ کالیبراسیون نباید خالی یا در آینده باشد.")
    cost = c.money(cost_amount)
    if cost < 0:
        raise ValueError("هزینه نمی‌تواند منفی باشد.")
    if result_code == "FAIL" and not (as_found or "").strip():
        raise ValueError("برای نتیجهٔ مردود، خطای یافت‌شده را بنویسید.")
    with new_session() as session:
        c.require(company_id, user_id, c.FORM_EXECUTE, session=session)
        inst = _get(session, company_id, instrument_id, lock=True)
        if inst.status_code == "RETIRED":
            raise ValueError("ابزار بازنشسته کالیبره نمی‌شود.")
        if inst.last_calibrated_on and calibrated_on < inst.last_calibrated_on:
            raise ValueError("تاریخ کالیبراسیون نباید پیش از آخرین کالیبراسیون ثبت‌شده باشد.")
        last_pass = session.scalar(select(CalibrationRecord.calibrated_on).where(
            CalibrationRecord.instrument_id == instrument_id, CalibrationRecord.result_code != "FAIL")
            .order_by(CalibrationRecord.calibrated_on.desc()).limit(1))
        rec = CalibrationRecord(company_id=company_id, instrument_id=instrument_id, calibrated_on=calibrated_on, result_code=result_code,
                                record_no=c.next_no(session, CalibrationRecord, CalibrationRecord.record_no, company_id),
                                performed_by=_clean(performed_by, 200), certificate_no=_clean(certificate_no, 100),
                                as_found=_clean(as_found, 500), as_left=_clean(as_left, 500), cost_amount=cost, notes=_clean(notes, 1000),
                                created_by_user_id=user_id)
        inst.last_calibrated_on = calibrated_on
        if result_code == "FAIL":
            inst.status_code = "OUT_OF_SERVICE"
            if open_ncr:
                from peecha.services.qms import ncr

                since = f"از {_jalali(last_pass)} (آخرین کالیبراسیون قبول)" if last_pass else "از ابتدای استفاده"
                rec.ncr_id = ncr._insert(session, company_id, user_id, ncr.NcrFields(
                    title=f"ابزار اندازه‌گیری {inst.code} {inst.name} در کالیبراسیون مردود شد"[:200], source_code="INTERNAL",
                    severity_code="MAJOR", cause_code="MEASUREMENT", responsible_user_id=inst.responsible_user_id,
                    description=f"خطای یافت‌شده: {(as_found or '').strip()}. اندازه‌گیری‌ها و پذیرش‌های انجام‌شده با این ابزار {since} "
                                "باید بررسی شود."), None).ncr_id
        else:
            inst.status_code = "ACTIVE" if inst.status_code == "OUT_OF_SERVICE" else inst.status_code
            inst.next_due_date = calibrated_on + datetime.timedelta(days=inst.interval_days)
            rec.next_due_date = inst.next_due_date
        session.add(rec)
        session.flush()
        c.audit(session, company_id, user_id, ENTITY, instrument_id, "COMPLETE" if result_code != "FAIL" else "REJECT",
                {"record_no": rec.record_no, "result": result_code, "next_due": inst.next_due_date, "ncr_id": rec.ncr_id})
        session.commit()
        return rec.record_id


def _jalali(day: datetime.date | None) -> str:
    from peecha import numerals

    return numerals.format_jalali_date(day) if day else ""


def state_of(row: CalibrationInstrument, today: datetime.date | None = None) -> str:
    if row.status_code != "ACTIVE":
        return row.status_code
    today = today or datetime.date.today()
    if row.next_due_date < today:
        return "OVERDUE"
    if row.next_due_date - datetime.timedelta(days=row.lead_days or 0) <= today:
        return "DUE"
    return "OK"


def is_usable(company_id: int, instrument_id: int) -> bool:
    """در خدمت و گذشته از سررسید نیست."""
    with new_session() as session:
        return state_of(_get(session, company_id, instrument_id)) in ("OK", "DUE")


def list_instruments(company_id: int, include_retired: bool = False, responsible_user_id: int | None = None) -> list[SimpleNamespace]:
    from peecha.db.models.fixed_assets import Asset

    with new_session() as session:
        q = select(CalibrationInstrument).where(CalibrationInstrument.company_id == company_id)
        if not include_retired:
            q = q.where(CalibrationInstrument.status_code != "RETIRED")
        if responsible_user_id:
            q = q.where(CalibrationInstrument.responsible_user_id == responsible_user_id)
        rows = list(session.scalars(q.order_by(CalibrationInstrument.next_due_date, CalibrationInstrument.code)))
        assets = {a.asset_id: c.asset_label(a) for a in session.scalars(select(Asset).where(
            Asset.asset_id.in_([r.asset_id for r in rows if r.asset_id] or [0])))}
        names = c.user_names(session, [r.responsible_user_id for r in rows])
        out = []
        for r in rows:
            state = state_of(r)
            out.append(SimpleNamespace(
                instrument_id=r.instrument_id, code=r.code, name=r.name, asset_id=r.asset_id, asset_label=assets.get(r.asset_id, ""),
                serial_no=r.serial_no or "", location_text=r.location_text or "", measure_range=r.measure_range or "",
                tolerance=r.tolerance or "", interval_days=r.interval_days, lead_days=r.lead_days, method_code=r.method_code,
                method_label=METHOD_LABELS[r.method_code], lab_detail_account_id=r.lab_detail_account_id,
                responsible_user_id=r.responsible_user_id, responsible=names.get(r.responsible_user_id, ""),
                status_code=r.status_code, status_label=STATUS_LABELS[r.status_code], next_due_date=r.next_due_date,
                last_calibrated_on=r.last_calibrated_on, notes=r.notes or "", state=state, state_label=STATE_LABELS[state]))
        return out


def get_instrument(company_id: int, instrument_id: int) -> SimpleNamespace:
    row = next((r for r in list_instruments(company_id, include_retired=True) if r.instrument_id == instrument_id), None)
    if row is None:
        raise ValueError("ابزار اندازه‌گیری نامعتبر است.")
    return row


def list_records(company_id: int, instrument_id: int) -> list[SimpleNamespace]:
    from peecha.db.models.quality import Nonconformance

    with new_session() as session:
        rows = list(session.scalars(select(CalibrationRecord).where(CalibrationRecord.company_id == company_id,
                                                                    CalibrationRecord.instrument_id == instrument_id)
                                    .order_by(CalibrationRecord.calibrated_on.desc(), CalibrationRecord.record_id.desc())))
        ncrs = {n.ncr_id: n.ncr_no for n in session.scalars(select(Nonconformance).where(
            Nonconformance.ncr_id.in_([r.ncr_id for r in rows if r.ncr_id] or [0])))}
        return [SimpleNamespace(record_id=r.record_id, record_no=r.record_no, calibrated_on=r.calibrated_on, result_code=r.result_code,
                                result_label=RESULT_LABELS[r.result_code], performed_by=r.performed_by or "",
                                certificate_no=r.certificate_no or "", as_found=r.as_found or "", as_left=r.as_left or "",
                                cost_amount=r.cost_amount, next_due_date=r.next_due_date, ncr_id=r.ncr_id, ncr_no=ncrs.get(r.ncr_id),
                                notes=r.notes or "")
                for r in rows]


def due_counts(company_id: int, responsible_user_id: int | None = None) -> dict[str, int]:
    counts = {"OVERDUE": 0, "DUE": 0, "OUT_OF_SERVICE": 0}
    for r in list_instruments(company_id, responsible_user_id=responsible_user_id):
        if r.state in counts:
            counts[r.state] += 1
    return counts
