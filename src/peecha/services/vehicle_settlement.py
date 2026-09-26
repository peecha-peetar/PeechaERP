"""تسویهٔ پایانِ روزِ خودرو (فازِ ۲، بخشِ ۲ از پخشِ گرم) -- طبقِ درخواستِ
صریحِ کاربر: «تسویه آخر روز باید بصورت انتخابی به یک نفر از ۳ تا نقش
واگذار بشه و تسویه را باید به تاییدِ انبار و حسابداری برسونه». هم‌الگو
با گیتِ warehouse_approved_at/weighing_approved_atِ پخشِ سرد
(commercial_documents.convert_to_invoice): دو تاییدِ مستقل، هرکدام
توسطِ یک نقشِ سازمانیِ متفاوت، پیش از قطعی‌شدنِ اثرِ انبار."""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field

from sqlalchemy import func, select

from peecha.db.base import new_session
from peecha.db.models.commercial import CommercialDocument, CommercialDocumentLine
from peecha.db.models.inventory import (
    VehicleLoading,
    VehicleLoadingLine,
    VehicleSettlement,
    VehicleSettlementLine,
    VehicleSettlementSettings,
)
from peecha.services import inventory_documents as inv_documents_service
from peecha.services import vehicle_team as vehicle_team_service

_ZERO = decimal.Decimal(0)


def get_settlement_role(company_id: int) -> str | None:
    with new_session() as session:
        row = session.get(VehicleSettlementSettings, company_id)
        return row.settlement_role_code if row else None


def set_settlement_role(company_id: int, role_code: str) -> None:
    if role_code not in vehicle_team_service.ROLE_CODES:
        raise ValueError("نقش نامعتبر است.")
    with new_session() as session:
        row = session.get(VehicleSettlementSettings, company_id)
        if row is None:
            session.add(VehicleSettlementSettings(company_id=company_id, settlement_role_code=role_code))
        else:
            row.settlement_role_code = role_code
        session.commit()


def get_settlement_vehicle_for_user(user_id: int, company_id: int) -> int | None:
    """هم‌الگو با can_submit_settlement، ولی بدونِ دانستنِ خودرو از قبل --
    اپِ موبایل/API این را صدا می‌زند تا بفهمد این کاربر (با هر نقشی که
    مسئولِ تسویه است) به کدام خودرو وصل است."""
    role_code = get_settlement_role(company_id)
    if role_code is None:
        return None
    return vehicle_team_service.get_assigned_vehicle_warehouse_id(user_id, company_id, role_code)


def can_submit_settlement(user_id: int, company_id: int, vehicle_warehouse_id: int) -> bool:
    """طبقِ درخواستِ صریح: فقط کسی که هم نقشِ تعیین‌شده (تنظیماتِ بالا)
    را دارد و هم واقعاً به همین خودرو (با همان نقش) وصل است، اجازهٔ
    ثبتِ تسویه دارد."""
    role_code = get_settlement_role(company_id)
    if role_code is None:
        return False
    assigned_vehicle = vehicle_team_service.get_assigned_vehicle_warehouse_id(user_id, company_id, role_code)
    return assigned_vehicle == vehicle_warehouse_id


@dataclass
class SettlementLineSummary:
    item_id: int
    uom_id: int
    loaded_quantity: decimal.Decimal
    sold_quantity: decimal.Decimal


def compute_today_summary(
    vehicle_warehouse_id: int, company_id: int, settlement_date: datetime.date,
    after: datetime.datetime | None = None,
) -> list[SettlementLineSummary]:
    """طبقِ نیازِ واقعیِ کاربر («سیستم پیشنهاد بدهد») -- بارگیریِ
    تاییدشدهٔ همین خودرو در همین تاریخ (loaded) در برابرِ فاکتورهایِ
    پست‌شده از همین انبار در همین تاریخ (sold). کسری/اضافیِ نهایی =
    loaded - sold - returnedِ اعلام‌شده (returned در submit_settlement
    گرفته می‌شود، نه این‌جا).

    after (طبقِ درخواستِ صریحِ کاربر «چند بار پخشِ گرم و تسویه در یک
    روز»): وقتی خودرو همان روز قبلاً یک‌بار تسویه شده، این تسویهٔ تازه
    فقط بارگیری/فروشِ *بعدِ* آن تسویهٔ قبلی را حساب می‌کند -- نه کلِ
    روز را دوباره (get_open_window_start همین مقدار را می‌دهد)."""
    with new_session() as session:
        loaded_stmt = (
            select(VehicleLoadingLine.item_id, VehicleLoadingLine.uom_id, func.sum(VehicleLoadingLine.planned_quantity))
            .join(VehicleLoading, VehicleLoading.vehicle_loading_id == VehicleLoadingLine.vehicle_loading_id)
            .where(
                VehicleLoading.vehicle_warehouse_id == vehicle_warehouse_id,
                VehicleLoading.company_id == company_id,
                VehicleLoading.loading_date == settlement_date,
                VehicleLoading.status_code == "CONFIRMED",
            )
        )
        sold_stmt = (
            select(CommercialDocumentLine.item_id, CommercialDocumentLine.uom_id, func.sum(CommercialDocumentLine.quantity))
            .join(CommercialDocument, CommercialDocument.document_id == CommercialDocumentLine.document_id)
            .where(
                CommercialDocument.company_id == company_id,
                CommercialDocument.warehouse_id == vehicle_warehouse_id,
                CommercialDocument.document_date == settlement_date,
                CommercialDocument.status_code == "POSTED",
            )
        )
        if after is not None:
            loaded_stmt = loaded_stmt.where(VehicleLoading.created_at > after)
            sold_stmt = sold_stmt.where(CommercialDocument.created_at > after)
        loaded_rows = session.execute(loaded_stmt.group_by(VehicleLoadingLine.item_id, VehicleLoadingLine.uom_id)).all()
        sold_rows = session.execute(sold_stmt.group_by(CommercialDocumentLine.item_id, CommercialDocumentLine.uom_id)).all()
    sold_by_item = {(item_id, uom_id): qty for item_id, uom_id, qty in sold_rows}
    result = []
    seen = set()
    for item_id, uom_id, qty in loaded_rows:
        seen.add((item_id, uom_id))
        result.append(SettlementLineSummary(item_id, uom_id, qty, sold_by_item.get((item_id, uom_id), _ZERO)))
    for (item_id, uom_id), qty in sold_by_item.items():
        if (item_id, uom_id) not in seen:
            result.append(SettlementLineSummary(item_id, uom_id, _ZERO, qty))
    return result


def compute_invoiced_amount(
    vehicle_warehouse_id: int, company_id: int, settlement_date: datetime.date,
    after: datetime.datetime | None = None,
) -> decimal.Decimal:
    with new_session() as session:
        stmt = select(func.sum(CommercialDocument.total_amount)).where(
            CommercialDocument.company_id == company_id,
            CommercialDocument.warehouse_id == vehicle_warehouse_id,
            CommercialDocument.document_date == settlement_date,
            CommercialDocument.status_code == "POSTED",
        )
        if after is not None:
            stmt = stmt.where(CommercialDocument.created_at > after)
        total = session.scalar(stmt)
        return total or _ZERO


def get_open_window_start(vehicle_warehouse_id: int, company_id: int, settlement_date: datetime.date) -> datetime.datetime | None:
    """طبقِ درخواستِ صریحِ کاربر («برایِ هر راننده در روز بتوانیم چند بار
    پخشِ گرم انجام و تسویه کنیم»): زمانِ ثبتِ آخرین تسویهٔ همین خودرو در
    همین تاریخ (هر وضعیتی) -- اگر امروز هنوز تسویه‌ای نداشته، None یعنی
    کلِ روز. today-summary (پیش‌نمایش) و submit_settlement (ثبتِ واقعی)
    باید دقیقاً همین پنجره را ببینند، وگرنه پیش‌نمایشِ موبایل با مبلغِ
    واقعاً ثبت‌شده فرق می‌کند."""
    with new_session() as session:
        return _last_settlement_submitted_at(session, vehicle_warehouse_id, company_id, settlement_date)


def _last_settlement_submitted_at(session, vehicle_warehouse_id: int, company_id: int, settlement_date: datetime.date) -> datetime.datetime | None:
    return session.scalar(
        select(func.max(VehicleSettlement.submitted_at)).where(
            VehicleSettlement.vehicle_warehouse_id == vehicle_warehouse_id,
            VehicleSettlement.company_id == company_id,
            VehicleSettlement.settlement_date == settlement_date,
        )
    )


@dataclass
class SettlementLineInput:
    item_id: int
    uom_id: int
    loaded_quantity: decimal.Decimal
    sold_quantity: decimal.Decimal
    returned_quantity: decimal.Decimal


@dataclass
class SettlementLineRow(SettlementLineInput):
    shortage_or_surplus: decimal.Decimal = field(default=_ZERO)


@dataclass
class SettlementRow:
    vehicle_settlement_id: int
    vehicle_warehouse_id: int
    settlement_date: datetime.date
    status_code: str
    invoiced_amount: decimal.Decimal
    declared_cash_amount: decimal.Decimal
    submitted_by_user_id: int
    # طبقِ درخواستِ صریحِ کاربر («چند بار پخشِ گرم و تسویه در یک روز»):
    # چون settlement_date دیگر یکتا نیست، ساعتِ ثبت برایِ تفکیکِ چند
    # تسویهٔ همان روز در فهرستِ دسکتاپ لازم است.
    submitted_at: datetime.datetime
    lines: list[SettlementLineRow]


def _to_row(s: VehicleSettlement, lines: list[VehicleSettlementLine]) -> SettlementRow:
    return SettlementRow(
        vehicle_settlement_id=s.vehicle_settlement_id, vehicle_warehouse_id=s.vehicle_warehouse_id,
        settlement_date=s.settlement_date, status_code=s.status_code, invoiced_amount=s.invoiced_amount,
        declared_cash_amount=s.declared_cash_amount, submitted_by_user_id=s.submitted_by_user_id,
        submitted_at=s.submitted_at,
        lines=[
            SettlementLineRow(
                l.item_id, l.uom_id, l.loaded_quantity, l.sold_quantity, l.returned_quantity,
                shortage_or_surplus=l.loaded_quantity - l.sold_quantity - l.returned_quantity,
            )
            for l in lines
        ],
    )


def get_settlement(vehicle_settlement_id: int, company_id: int) -> SettlementRow:
    with new_session() as session:
        s = session.get(VehicleSettlement, vehicle_settlement_id)
        if s is None or s.company_id != company_id:
            raise ValueError("سندِ تسویه نامعتبر است.")
        lines = session.scalars(
            select(VehicleSettlementLine).where(VehicleSettlementLine.vehicle_settlement_id == vehicle_settlement_id)
        ).all()
        return _to_row(s, lines)


def list_settlements(company_id: int, status_code: str | None = None) -> list[SettlementRow]:
    with new_session() as session:
        stmt = select(VehicleSettlement.vehicle_settlement_id).where(VehicleSettlement.company_id == company_id)
        if status_code is not None:
            stmt = stmt.where(VehicleSettlement.status_code == status_code)
        stmt = stmt.order_by(VehicleSettlement.settlement_date.desc(), VehicleSettlement.submitted_at.desc())
        ids = session.scalars(stmt).all()
    return [get_settlement(sid, company_id) for sid in ids]


def submit_settlement(
    vehicle_warehouse_id: int, company_id: int, submitted_by_user_id: int, settlement_date: datetime.date,
    lines: list[SettlementLineInput], declared_cash_amount: decimal.Decimal,
) -> int:
    if not can_submit_settlement(submitted_by_user_id, company_id, vehicle_warehouse_id):
        raise ValueError("شما مجازِ ثبتِ تسویهٔ این خودرو نیستید.")
    with new_session() as session:
        # طبقِ درخواستِ صریحِ کاربر («برایِ هر راننده در روز بتوانیم چند
        # بار پخشِ گرم انجام و تسویه کنیم»): دیگر یک تسویهٔ قطعیِ یکتا در
        # روز نیست -- هر تسویهٔ تازه فقط بارگیری/فروشِ بعدِ آخرین تسویهٔ
        # همین خودرو در همین تاریخ را حساب می‌کند (get_open_window_start).
        window_start = _last_settlement_submitted_at(session, vehicle_warehouse_id, company_id, settlement_date)

        # طبقِ درخواستِ صریح: مقصدِ برگشت همان انبارِ مبدأِ آخرین بارگیریِ
        # تاییدشدهٔ همین خودرو در همین تاریخ است (جایی که کالا از آن‌جا
        # بارگیری شده بود).
        last_loading = session.scalar(
            select(VehicleLoading)
            .where(
                VehicleLoading.vehicle_warehouse_id == vehicle_warehouse_id, VehicleLoading.company_id == company_id,
                VehicleLoading.loading_date == settlement_date, VehicleLoading.status_code == "CONFIRMED",
            )
            .order_by(VehicleLoading.vehicle_loading_id.desc())
        )
        if last_loading is None:
            raise ValueError("برایِ این خودرو در این تاریخ هیچ بارگیریِ تاییدشده‌ای ثبت نشده است.")

        invoiced_amount = compute_invoiced_amount(vehicle_warehouse_id, company_id, settlement_date, after=window_start)
        settlement = VehicleSettlement(
            company_id=company_id, vehicle_warehouse_id=vehicle_warehouse_id,
            return_destination_warehouse_id=last_loading.source_warehouse_id, settlement_date=settlement_date,
            invoiced_amount=invoiced_amount, declared_cash_amount=declared_cash_amount,
            submitted_by_user_id=submitted_by_user_id,
        )
        session.add(settlement)
        session.flush()
        for line in lines:
            session.add(
                VehicleSettlementLine(
                    vehicle_settlement_id=settlement.vehicle_settlement_id, item_id=line.item_id, uom_id=line.uom_id,
                    loaded_quantity=line.loaded_quantity, sold_quantity=line.sold_quantity,
                    returned_quantity=line.returned_quantity,
                )
            )
        session.commit()
        return settlement.vehicle_settlement_id


def approve_warehouse(vehicle_settlement_id: int, company_id: int, approved_by_user_id: int) -> None:
    with new_session() as session:
        s = session.get(VehicleSettlement, vehicle_settlement_id)
        if s is None or s.company_id != company_id:
            raise ValueError("سندِ تسویه نامعتبر است.")
        if s.status_code != "SUBMITTED":
            raise ValueError("این تسویه در وضعیتِ قابلِ‌تاییدِ انبار نیست.")
        s.status_code = "WAREHOUSE_APPROVED"
        s.warehouse_approved_by_user_id = approved_by_user_id
        s.warehouse_approved_at = datetime.datetime.now()
        session.commit()


def approve_accounting(vehicle_settlement_id: int, company_id: int, approved_by_user_id: int) -> int | None:
    """تاییدِ نهایی -- طبقِ درخواستِ صریح («تسویه را باید به تاییدِ انبار
    و حسابداری برسونه»): فقط بعدِ این تایید، سندِ TRANSFERِ واقعی (خودرو
    -> انبارِ مقصد) ساخته/تایید/پست می‌شود -- عمداً TRANSFER است، نه
    RETURN_IN: این کالاها هرگز فروخته نشده‌اند (پس «برگشتِ کالایِ
    فروخته‌شده» نیستند، صرفاً جابه‌جاییِ فیزیکی‌اند)، هم‌الگو با
    vehicle_loading.confirm_vehicle_loading (که همان مسیر را برعکس طی
    می‌کند) -- بدونِ نیاز به کدِ دلیل یا بهایِ واحدِ دستی، چون میانگینِ
    بهایِ موجود رویِ خودِ انبارِ خودرو حفظ می‌شود. اگر هیچ ردیفی مقدارِ
    برگشتی نداشته باشد (همه فروخته/کسری)، سندِ انبار لازم نیست -- None
    برمی‌گردد."""
    with new_session() as session:
        s = session.get(VehicleSettlement, vehicle_settlement_id)
        if s is None or s.company_id != company_id:
            raise ValueError("سندِ تسویه نامعتبر است.")
        if s.status_code != "WAREHOUSE_APPROVED":
            raise ValueError("این تسویه هنوز تاییدِ انبار نگرفته است.")
        vehicle_warehouse_id = s.vehicle_warehouse_id
        return_destination_warehouse_id = s.return_destination_warehouse_id
        lines = [
            (l.item_id, l.uom_id, l.returned_quantity)
            for l in session.scalars(
                select(VehicleSettlementLine).where(VehicleSettlementLine.vehicle_settlement_id == vehicle_settlement_id)
            ).all()
            if l.returned_quantity > 0
        ]

    return_stock_document_id = None
    if lines:
        return_stock_document_id = inv_documents_service.create_stock_document(
            company_id, approved_by_user_id, "TRANSFER", datetime.date.today(),
            inv_documents_service.DocumentHeaderFields(
                source_warehouse_id=vehicle_warehouse_id, destination_warehouse_id=return_destination_warehouse_id,
            ),
        )
        for item_id, uom_id, quantity in lines:
            inv_documents_service.add_line(
                return_stock_document_id, company_id,
                inv_documents_service.LineFields(item_id=item_id, uom_id=uom_id, quantity=quantity, quantity_base=quantity),
            )
        inv_documents_service.confirm_stock_document(return_stock_document_id, company_id)
        inv_documents_service.post_stock_document(return_stock_document_id, company_id, approved_by_user_id)

    with new_session() as session:
        s = session.get(VehicleSettlement, vehicle_settlement_id)
        s.status_code = "ACCOUNTING_APPROVED"
        s.accounting_approved_by_user_id = approved_by_user_id
        s.accounting_approved_at = datetime.datetime.now()
        s.return_stock_document_id = return_stock_document_id
        session.commit()
    return return_stock_document_id
