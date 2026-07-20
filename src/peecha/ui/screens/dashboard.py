"""داشبورد اصلی — کارت‌های KPI و نمودارها، همه از دیتابیس واقعی.

طبق docs/ui-ux-guidelines.md بخش ۱۰، ولی چون هنوز فروش/انبار ساخته نشده،
KPIها و نمودارها به چیزهایی محدود شده‌اند که همین حالا واقعی/صادقانه
قابل‌محاسبه‌اند (نه اعداد نمونه‌ای طرح اولیه).
"""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import dashboard as dashboard_service
from peecha.ui import numerals, theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape

_KV_PATH = os.path.join(os.path.dirname(__file__), "dashboard.kv")
Builder.load_file(_KV_PATH)

_DONUT_COLORS = [theme.ACCENT, theme.SUCCESS, theme.CHART_PURPLE, theme.CHART_ORANGE, theme.WARNING]


class DashboardScreen(MDScreen):
    def on_pre_enter(self, *args):
        self.refresh()

    def refresh(self) -> None:
        company_id = session.current_company.company_id if session.current_company else None

        self.ids.card_companies.value = numerals.to_persian_digits(str(dashboard_service.count_companies()))
        self.ids.card_users.value = numerals.to_persian_digits(str(dashboard_service.count_users()))
        self.ids.card_accounts.value = numerals.to_persian_digits(
            str(dashboard_service.count_chart_of_accounts(company_id))
        )
        self.ids.card_entries.value = numerals.to_persian_digits(
            str(dashboard_service.count_journal_entries(company_id))
        )

        labels, values = dashboard_service.journal_entries_per_month(company_id)
        if any(values):
            self.ids.entries_chart.labels = labels
            self.ids.entries_chart.series = [
                {"name": shape(tr("تعداد اسناد")), "color": theme.ACCENT, "values": [float(v) for v in values]}
            ]
            self.ids.entries_chart_empty.text = ""
        else:
            self.ids.entries_chart.series = []
            self.ids.entries_chart_empty.text = shape(tr("هنوز سند حسابداری‌ای ثبت نشده است."))

        breakdown = dashboard_service.chart_of_accounts_by_category(company_id)
        if breakdown:
            self.ids.accounts_donut.segments = [
                {"label": label, "value": float(count), "color": _DONUT_COLORS[i % len(_DONUT_COLORS)]}
                for i, (label, count) in enumerate(breakdown)
            ]
            self.ids.accounts_legend.text = "\n".join(
                shape(f"⬤ {label} — {numerals.to_persian_digits(str(count))}") for label, count in breakdown
            )
            self.ids.accounts_donut_empty.text = ""
        else:
            self.ids.accounts_donut.segments = []
            self.ids.accounts_legend.text = ""
            self.ids.accounts_donut_empty.text = shape(tr("هنوز حسابی در کدینگ حسابداری تعریف نشده است."))
