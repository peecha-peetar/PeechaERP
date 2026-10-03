"""ترازنامه — دارایی‌ها/بدهی‌ها/حقوقِ صاحبانِ سهام تا یک تاریخِ مشخص
(«تا تاریخ» در نوارِ فیلترِ مشترک به‌عنوانِ تاریخِ ترازنامه استفاده می‌شود؛
«از تاریخ» در این گزارش اثری ندارد، چون ترازنامه مانده‌یِ تجمعی است، نه
گردشِ یک بازه).

طبقِ درخواستِ صریح (عکسِ پیوست): چیدمانِ کلاسیکِ دوستونی — راست/چپ، به‌جایِ
فهرستِ عمودیِ قبلی. این‌که هر گروه در کدام ستون بیاید از
services.reports.compute_balance_sheet (فیلدِ side_code، قابلِ‌پیکربندی
در تنظیماتِ نگاشتِ صورت‌هایِ مالی) می‌آید."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import QMessageBox

from peecha import numerals, session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import currencies as currencies_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase, code_in_range


class BalanceSheetScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("ترازنامه (تا «تا تاریخ»)")
        self.enable_code_range_filter()
        self.enable_cost_center_filter()
        self.enable_jasper_report("BALANCE_SHEET")
        self._currency_decimal_places = 0

    def code_range_account_level(self) -> int | None:
        # ردیف‌هایِ ترازنامه همیشه حساب‌هایِ سطحِ کل (رول‌آپ‌شده) هستند.
        return 2

    def refresh(self) -> None:
        company = session.current_company
        currency = None
        if company is not None:
            currency = next(
                (c for c in currencies_service.list_all_currencies() if c.currency_id == company.base_currency_id),
                None,
            )
        self._currency_decimal_places = currency.decimal_places if currency else 0
        super().refresh()

    def _fmt(self, value: decimal.Decimal) -> str:
        return numerals.format_money(value, self._currency_decimal_places, None)

    def _grouped_lines(self, rows: list, groups_by_id: dict[int, "coa_service.AccountRow"]) -> list[tuple[str, str, str]]:
        """طبقِ آیتمِ ۲ («ترازنامه به ترتیبِ گروهِ حساب‌ها، با کدهایِ کلِ زیرِ
        هر گروه و جمعِ کلِ هر گروه بیاید»): ردیف‌هایِ کل (سطحِ ۲) زیرِ گروهِ
        (سطحِ ۱) خودشان، به ترتیبِ کدِ گروه، با یک ردیفِ جمعِ فرعی برایِ هر
        گروه — عیناً همان ساختاری که در «نگاشتِ صورت‌هایِ مالی» تعریف شده،
        بدونِ هیچ بخشِ اضافه‌ای (مثلِ انتظامی که جزوِ ترازنامه‌ی استاندارد نیست)."""
        rows_by_group: dict[int, list] = {}
        for r in rows:
            rows_by_group.setdefault(r.parent_account_id, []).append(r)
        lines: list[tuple[str, str, str]] = []
        for group_id in sorted(rows_by_group, key=lambda gid: groups_by_id[gid].full_code if gid in groups_by_id else ""):
            group_rows = rows_by_group[group_id]
            group = groups_by_id.get(group_id)
            lines.append((group.full_code if group else "", group.name if group else "", ""))
            subtotal = decimal.Decimal(0)
            for r in sorted(group_rows, key=lambda r: r.full_code):
                lines.append((r.full_code, r.name, self._fmt(r.balance)))
                subtotal += r.balance
            lines.append(("", f"جمعِ {group.name if group else ''}", self._fmt(subtotal)))
        return lines

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        code_from, code_to = self.code_range()
        result = reports_service.compute_balance_sheet(
            company_id, date_to, status_filter=self.status_filter(), cost_center_id=self.cost_center_id()
        )
        groups_by_id = {a.account_id: a for a in coa_service.list_accounts(company_id) if a.account_level == 1}

        def in_range(r):
            return code_in_range(r.full_code, code_from, code_to)

        all_rows = [r for r in (result.asset_rows + result.liability_rows + result.equity_rows) if in_range(r)]
        right_rows = [r for r in all_rows if r.side_code == "RIGHT"]
        left_rows = [r for r in all_rows if r.side_code == "LEFT"]

        right_lines = self._grouped_lines(right_rows, groups_by_id)
        left_lines = self._grouped_lines(left_rows, groups_by_id)

        total_right = sum((r.balance for r in right_rows), decimal.Decimal(0))
        total_left = sum((r.balance for r in left_rows), decimal.Decimal(0)) + result.accumulated_earnings
        left_lines.append(("", "سودِ (زیانِ) انباشته", self._fmt(result.accumulated_earnings)))
        left_lines.append(("", "جمعِ کل", self._fmt(total_left)))
        right_lines.append(("", "جمعِ کل", self._fmt(total_right)))

        headers = ["کدِ راست", "نامِ راست (دارایی‌ها)", "مبلغِ راست", "کدِ چپ", "نامِ چپ (بدهی‌ها و حقوقِ صاحبانِ سهام)", "مبلغِ چپ"]
        row_count = max(len(right_lines), len(left_lines))
        table_rows: list[list] = []
        for i in range(row_count):
            r_code, r_name, r_amount = right_lines[i] if i < len(right_lines) else ("", "", "")
            l_code, l_name, l_amount = left_lines[i] if i < len(left_lines) else ("", "", "")
            table_rows.append([r_code, r_name, r_amount, l_code, l_name, l_amount])

        balance_note = "متوازن" if total_right == total_left else "نامتوازن!"
        footer = ["", f"جمعِ راست: {self._fmt(total_right)}", "", "", f"جمعِ چپ: {self._fmt(total_left)}", balance_note]
        return headers, table_rows, footer

    def _build_jasper_rows_and_params(self) -> tuple[list[dict], dict] | None:
        if not self._rows:
            QMessageBox.information(self, "گزارش", "داده‌ای برایِ چاپ وجود ندارد.")
            return None

        field_names = ["right_code", "right_name", "right_amount_display", "left_code", "left_name", "left_amount_display"]
        print_rows = [dict(zip(field_names, row)) for row in self._rows]
        company = session.current_company
        footer = self._footer or ["", "", "", "", "", ""]
        params = {
            "companyName": company.display_name if company else "",
            "dateLabel": f"تا تاریخِ {numerals.format_jalali_date(self.date_to.date())}",
            "generatedAt": numerals.format_jalali_datetime(datetime.datetime.now()),
            "totalRightLine": footer[1],
            "totalLeftLine": footer[4],
            "balanceNote": footer[5],
        }
        return print_rows, params
