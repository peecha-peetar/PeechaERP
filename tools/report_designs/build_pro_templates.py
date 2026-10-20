"""R320: ساخت قالب‌های «طرح حرفه‌ای» Jasper (راست‌به‌چپ، فارسی) از روی قالب‌های پایه.

هر قالب حرفه‌ای همان پارامترها و فیلدهای قالب پایه را دارد (از خود فایل پایه برداشته می‌شود)، پس کد چاپ تغییری نمی‌خواهد؛
فقط چیدمان عوض می‌شود: نوار عنوان رنگی، کارت اطلاعات سند، جدول راست‌به‌چپ با ردیف‌های راه‌راه، جعبهٔ جمع، جای امضا
و پانویس «صفحهٔ x از y» با رقم فارسی.

اجرا (فقط هنگام تغییر طرح): python3 tools/report_designs/build_pro_templates.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "peecha" / "reporting" / "templates"

NAVY, NAVY_SOFT, LINE, ZEBRA, PAPER = "#1F3A5F", "#E8EEF6", "#C9D3E0", "#F6F8FB", "#FFFFFF"
_FA = "".join(f'.replace("{d}","{"۰۱۲۳۴۵۶۷۸۹"[d]}")' for d in range(10))


def fa_num(expr: str) -> str:
    return f"String.valueOf({expr}){_FA}"


def present(expr: str) -> str:
    return f"{expr} != null && !{expr}.isEmpty()"


@dataclass
class Col:
    header: str
    field: str
    width: int
    align: str = "Center"


@dataclass
class Spec:
    base: str
    out: str
    landscape: bool
    title: str  # عبارت جاوا
    company: str  # عبارت جاوا
    meta: list[tuple[str, str]]  # (برچسب، عبارت پارامتر رشته‌ای)
    cols: list[Col]  # از راست به چپ
    totals_row: dict[int, str] = field(default_factory=dict)  # اندیس ستون ← عبارت
    totals_label_span: int = 0  # چند ستون اول (از راست) برای برچسب «جمع کل»
    totals_box: list[tuple[str, str, bool]] = field(default_factory=list)  # (برچسب، عبارت، اختیاری)
    grand_total: tuple[str, str] | None = None
    notes: list[tuple[str, str]] = field(default_factory=list)  # (پیشوند، عبارت)
    signatures: list[str] = field(default_factory=list)
    parties: bool = False  # فروشنده/خریدار (فاکتور)


def _declarations(base: str) -> str:
    text = (TEMPLATES / base).read_text(encoding="utf-8")
    blocks = re.findall(r"(<parameter\b.*?</parameter>|<parameter\b[^>]*/>|<field\b.*?</field>|<field\b[^>]*/>)", text, re.S)
    return "\n".join("    " + b.strip() for b in blocks)


def _text(x, y, w, h, expr, style="Cell", align="Right", static=False, when=None, color=None, mode=None, bg=None,
          extra="", indent=4):
    attrs = f'style="{style}" x="{x}" y="{y}" width="{w}" height="{h}"'
    if color:
        attrs += f' forecolor="{color}"'
    if mode:
        attrs += f' mode="{mode}" backcolor="{bg}"'
    pwe = f"<printWhenExpression><![CDATA[{when}]]></printWhenExpression>" if when else ""
    elem = f"<reportElement {attrs}>{pwe}</reportElement>" if pwe else f"<reportElement {attrs}/>"
    para = f'<paragraph rightIndent="{indent}" leftIndent="{indent}"/>'
    te = f'<textElement textAlignment="{align}" verticalAlignment="Middle">{para}</textElement>'
    if static:
        return f"<staticText>{elem}{te}<text><![CDATA[{expr}]]></text></staticText>"
    return f'<textField{extra}>{elem}{te}<textFieldExpression><![CDATA[{expr}]]></textFieldExpression></textField>'


def _rect(x, y, w, h, bg, line=None, radius=0, when=None):
    pen = f'<graphicElement><pen lineWidth="{0.6 if line else 0}" lineColor="{line or bg}"/></graphicElement>'
    pwe = f"<printWhenExpression><![CDATA[{when}]]></printWhenExpression>" if when else ""
    return (f'<rectangle radius="{radius}"><reportElement x="{x}" y="{y}" width="{w}" height="{h}" mode="Opaque" '
            f'backcolor="{bg}" forecolor="{line or bg}">{pwe}</reportElement>{pen}</rectangle>')


def _line(x, y, w, color=LINE):
    return f'<line><reportElement x="{x}" y="{y}" width="{w}" height="1" forecolor="{color}"/></line>'


def _logo(x, y, side):
    when = f'$P{{companyLogoPath}} != null && !$P{{companyLogoPath}}.isEmpty() && "{side}".equals($P{{companyLogoPosition}})'
    return (f'<image scaleImage="RetainShape" hAlign="Center" vAlign="Middle" onErrorType="Blank"><reportElement x="{x}" '
            f'y="{y}" width="56" height="40"><printWhenExpression><![CDATA[{when}]]></printWhenExpression></reportElement>'
            f'<imageExpression><![CDATA[$P{{companyLogoPath}}]]></imageExpression></image>')


def build(spec: Spec) -> str:
    pw, ph = (842, 595) if spec.landscape else (595, 842)
    margin = 20 if spec.landscape else 28
    W = pw - 2 * margin
    out = []
    # --- سرصفحه: نوار عنوان + کارت اطلاعات -----------------------------------------------------------
    h = []
    h.append(_rect(0, 0, W, 50, NAVY, radius=4))
    h.append(_logo(W - 62, 5, "RIGHT"))
    h.append(_logo(6, 5, "LEFT"))
    h.append(_text(70, 4, W - 140, 24, spec.title, "Title", "Center", color=PAPER))
    h.append(_text(70, 28, W - 140, 18, spec.company, "TitleMeta", "Center", color="#D6E2F2"))
    y = 58
    if spec.parties:
        half = (W - 8) // 2
        for x, label, lines in (
                (W - half, "فروشنده", ["$P{companyLegalName}", "$P{companyIdsLine}"]),
                (0, "خریدار / طرف حساب", ["$P{counterpartyLabel}", "$P{counterpartyIdsLine}", "$P{counterpartyContactLine}",
                                         "$P{counterpartyAddress}"])):
            h.append(_rect(x, y, half, 76, PAPER, LINE, radius=4))
            h.append(_rect(x, y, half, 16, NAVY_SOFT, radius=4))
            h.append(_text(x, y, half, 16, label, "BoxTitle", "Right", static=True))
            # ارتفاع خط پررنگ باید جای کامل قلم را داشته باشد وگرنه Jasper آن را چاپ نمی‌کند
            h.append(_text(x, y + 17, half, 17, lines[0], "BoxStrong", "Right", when=present(lines[0])))
            for i, expr in enumerate(lines[1:]):
                h.append(_text(x, y + 34 + i * 13, half, 13, expr, "BoxText", "Right", when=present(expr)))
        y += 84
    per_row = 6 if spec.landscape else 5
    rows = [spec.meta[i:i + per_row] for i in range(0, len(spec.meta), per_row)]
    for row in rows:
        cell_w = W // max(len(rows[0]), 2)
        h.append(_rect(0, y, W, 30, NAVY_SOFT, radius=4))
        for i, (label, expr) in enumerate(row):
            x = W - (i + 1) * cell_w
            h.append(_text(x, y + 1, cell_w, 13, label, "MetaLabel", "Right", static=True, when=present(expr)))
            h.append(_text(x, y + 14, cell_w, 15, expr, "MetaValue", "Right", when=present(expr),
                           extra=' textAdjust="ScaleFont"'))
        y += 34
    out.append(f'    <pageHeader>\n        <band height="{y + 4}">\n            ' + "\n            ".join(h)
               + "\n        </band>\n    </pageHeader>")
    # --- سرستون و ردیف‌ها (اولین ستون سمت راست) ------------------------------------------------------------
    xs, x = [], W
    for c in spec.cols:
        x -= c.width
        xs.append(x)
    ch = [_rect(0, 0, W, 22, NAVY)]
    for c, cx in zip(spec.cols, xs):
        ch.append(_text(cx, 0, c.width, 22, c.header, "Header", "Center", static=True, color=PAPER, indent=2))
    out.append('    <columnHeader>\n        <band height="22">\n            ' + "\n            ".join(ch)
               + "\n        </band>\n    </columnHeader>")
    det = [_rect(0, 0, W, 18, ZEBRA, when="$V{REPORT_COUNT} % 2 == 0"), _line(0, 17, W)]
    for c, cx in zip(spec.cols, xs):
        det.append(_text(cx, 0, c.width, 17, f"$F{{{c.field}}}", "Cell", c.align,
                         extra=' textAdjust="ScaleFont"', indent=3))
    out.append('    <detail>\n        <band height="18">\n            ' + "\n            ".join(det)
               + "\n        </band>\n    </detail>")
    # --- پانویس --------------------------------------------------------------------------------------------
    # «صفحهٔ x از y» در یک خانه؛ evaluationTime="Master" شمارهٔ صفحه و تعداد کل را هنگام خروجی می‌دهد
    page = ('"صفحهٔ " + ' + fa_num("$V{MASTER_CURRENT_PAGE}") + ' + " از " + ' + fa_num("$V{MASTER_TOTAL_PAGES}"))
    pf = [_line(0, 2, W, NAVY),
          _text(W - 160, 5, 160, 14, page, "Footer", "Right", extra=' evaluationTime="Master"', indent=1),
          _text(0, 5, W - 170, 14, '"تاریخ چاپ: " + $P{generatedAt}', "Footer", "Left", when=present("$P{generatedAt}"))]
    out.append('    <pageFooter>\n        <band height="20">\n            ' + "\n            ".join(pf)
               + "\n        </band>\n    </pageFooter>")
    # --- خلاصه: ردیف جمع، جعبهٔ جمع، توضیحات، امضا ---------------------------------------------------------
    s, y = [], 6
    if spec.totals_row:
        s.append(_rect(0, y, W, 22, NAVY_SOFT, LINE))
        label_w = sum(c.width for c in spec.cols[:spec.totals_label_span])
        s.append(_text(W - label_w, y, label_w, 22, "جمع کل", "TotalLabel", "Center", static=True))
        for idx, expr in spec.totals_row.items():
            s.append(_text(xs[idx], y, spec.cols[idx].width, 22, expr, "TotalValue", "Center", extra=' textAdjust="ScaleFont"',
                           indent=2))
        y += 30
    box_top = y
    if spec.totals_box or spec.grand_total:
        bw, lw = 230, 110
        for label, expr, optional in spec.totals_box:
            when = present(expr) if optional else None
            s.append(_text(lw, y, bw - lw, 18, expr, "TotalValue", "Left", when=when))
            s.append(_text(bw - lw, y, lw, 18, label, "TotalLabel", "Right", static=True, when=when))
            s.append(_line(0, y + 18, bw))
            y += 20
        if spec.grand_total:
            label, expr = spec.grand_total
            s.append(_rect(0, y + 2, bw, 26, NAVY, radius=4))
            s.append(_text(0, y + 2, bw - lw, 26, expr, "GrandValue", "Left", color=PAPER))
            is_expr = label.startswith("$P{")
            s.append(_text(bw - lw, y + 2, lw, 26, label, "GrandLabel", "Right", static=not is_expr, color=PAPER))
            y += 32
        notes_x, notes_w, ny = bw + 12, W - bw - 12, box_top
    else:
        notes_x, notes_w, ny = 0, W, y
    for prefix, expr in spec.notes:
        s.append(_text(notes_x, ny, notes_w, 18, f'"{prefix}" + {expr}', "Note", "Right", when=present(expr)))
        ny += 20
    y = max(y, ny) + 8
    if spec.signatures:
        n = len(spec.signatures)
        sw = (W - (n - 1) * 16) // n
        for i, label in enumerate(spec.signatures):
            sx = W - (i + 1) * sw - i * 16
            s.append(_rect(sx, y, sw, 52, PAPER, LINE, radius=4))
            s.append(_text(sx, y + 2, sw, 14, label, "BoxTitle", "Center", static=True))
        y += 56
    out.append(f'    <summary>\n        <band height="{max(y, 10)}">\n            ' + "\n            ".join(s)
               + "\n        </band>\n    </summary>")
    styles = f"""    <style name="Default" isDefault="true" fontName="Vazirmatn" fontSize="8"/>
    <style name="Title" fontName="Vazirmatn" fontSize="15" isBold="true"/>
    <style name="TitleMeta" fontName="Vazirmatn" fontSize="8"/>
    <style name="BoxTitle" fontName="Vazirmatn" fontSize="8" isBold="true" forecolor="{NAVY}"/>
    <style name="BoxStrong" fontName="Vazirmatn" fontSize="9" isBold="true"/>
    <style name="BoxText" fontName="Vazirmatn" fontSize="7.5"/>
    <style name="MetaLabel" fontName="Vazirmatn" fontSize="7" forecolor="#5A6B82"/>
    <style name="MetaValue" fontName="Vazirmatn" fontSize="9" isBold="true"/>
    <style name="Header" fontName="Vazirmatn" fontSize="8" isBold="true"/>
    <style name="Cell" fontName="Vazirmatn" fontSize="8"/>
    <style name="TotalLabel" fontName="Vazirmatn" fontSize="8.5" isBold="true" forecolor="{NAVY}"/>
    <style name="TotalValue" fontName="Vazirmatn" fontSize="8.5" isBold="true"/>
    <style name="GrandLabel" fontName="Vazirmatn" fontSize="10.5" isBold="true"/>
    <style name="GrandValue" fontName="Vazirmatn" fontSize="11" isBold="true"/>
    <style name="Note" fontName="Vazirmatn" fontSize="8"/>
    <style name="Footer" fontName="Vazirmatn" fontSize="7" forecolor="#5A6B82"/>"""
    orient = ' orientation="Landscape"' if spec.landscape else ""
    head = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- R320: طرح حرفه‌ای (راست‌به‌چپ) — ساخته‌شده با tools/report_designs/build_pro_templates.py از {spec.base}؛
     پارامترها و فیلدها همان قالب پایه است. -->
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
              xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
              xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports http://jasperreports.sourceforge.net/xsd/jasperreport.xsd"
              name="{spec.out.removesuffix('.jrxml')}" pageWidth="{pw}" pageHeight="{ph}"{orient}
              columnWidth="{W}" leftMargin="{margin}" rightMargin="{margin}" topMargin="20" bottomMargin="20"
              whenNoDataType="AllSectionsNoDetail">
{styles}
{_declarations(spec.base)}
"""
    return head + "\n".join(out) + "\n</jasperReport>\n"


DOC_TITLE = '$P{documentTypeLabel} + "   شمارهٔ " + $P{documentNoDisplay}'

SPECS = [
    Spec("invoice.jrxml", "invoice_pro.jrxml", False, DOC_TITLE, "$P{companyDisplayName}",
         [("تاریخ", "$P{documentDateDisplay}"), ("سررسید", "$P{dueDateDisplay}"), ("وضعیت", "$P{statusLabel}"),
          ("ارجاع", "$P{referenceNo}"), ("انبار", "$P{warehouseName}")],
         [Col("ردیف", "row_no_display", 28), Col("شرح کالا و خدمات", "item_label", 150, "Right"), Col("واحد", "uom_display", 40),
          Col("مقدار", "quantity_display", 48), Col("فی واحد", "unit_price_display", 70), Col("تخفیف", "discount_display", 58),
          Col("مالیات و عوارض", "tax_display", 58), Col("مبلغ کل", "line_total_display", 87)],
         totals_box=[("جمع جزء", "$P{subtotalDisplay}", False), ("تخفیف", "$P{discountDisplay}", False),
                     ("مالیات و عوارض", "$P{taxDisplay}", False), ("هزینهٔ حمل", "$P{shippingDisplay}", True)],
         grand_total=("جمع کل", "$P{totalDisplay}"),
         notes=[("مبلغ به حروف: ", "$P{totalInWordsDisplay}"), ("توضیح: ", "$P{headerDescription}")],
         signatures=["مهر و امضای فروشنده", "امضای خریدار"], parties=True),
    Spec("stock_document.jrxml", "stock_document_pro.jrxml", False, DOC_TITLE, "$P{companyDisplayName}",
         [("تاریخ", "$P{documentDateDisplay}"), ("وضعیت", "$P{statusLabel}"), ("طرف حساب", "$P{counterpartyLabel}"),
          ("ارجاع", "$P{referenceNo}"), ("از انبار", "$P{sourceWarehouseName}"), ("به انبار", "$P{destinationWarehouseName}")],
         [Col("ردیف", "row_no_display", 28), Col("کالا", "item_label", 150, "Right"), Col("واحد", "uom_display", 40),
          Col("مقدار", "quantity_display", 55), Col("بهای واحد", "unit_cost_display", 70), Col("بهای کل", "line_total_display", 80),
          Col("دلیل", "reason_display", 56), Col("توضیح", "description", 60, "Right")],
         totals_box=[("جمع بهای کل", "$P{totalCostDisplay}", True)],
         notes=[("توضیح: ", "$P{headerDescription}")], signatures=["تحویل‌دهنده", "تحویل‌گیرنده", "انباردار"]),
    Spec("kardex.jrxml", "kardex_pro.jrxml", True, '"کاردکس کالا"', "$P{companyName}",
         [("کالا", "$P{itemName}"), ("انبار", "$P{warehouseName}"), ("بازهٔ گزارش", "$P{dateRangeLabel}")],
         [Col("تاریخ", "movement_date_display", 70), Col("نوع سند", "document_type_label", 65, "Right"),
          Col("شماره", "document_no_display", 45), Col("انبار", "warehouse_name", 70, "Right"),
          Col("طرف حساب", "counterparty_label", 90, "Right"), Col("ورود", "quantity_in_display", 45),
          Col("خروج", "quantity_out_display", 45), Col("بهای واحد", "unit_cost_display", 65),
          Col("بهای کل ورود", "value_in_display", 68), Col("بهای کل خروج", "value_out_display", 68),
          Col("قیمت فروش", "sale_price_display", 60), Col("مانده", "running_balance_display", 45),
          Col("ماندهٔ ریالی", "running_value_balance_display", 66)]),
    Spec("trial_balance.jrxml", "trial_balance_pro.jrxml", True, '"تراز آزمایشی"', "$P{companyName}",
         [("بازهٔ گزارش", "$P{dateRangeLabel}"), ("سطح حساب", "$P{levelLabel}")],
         [Col("کد", "account_code", 60), Col("نام حساب", "account_name", 150, "Right"),
          Col("ماندهٔ ابتدای دوره (بدهکار)", "opening_debit_display", 98),
          Col("ماندهٔ ابتدای دوره (بستانکار)", "opening_credit_display", 98), Col("گردش بدهکار", "period_debit_display", 98),
          Col("گردش بستانکار", "period_credit_display", 98), Col("ماندهٔ پایان دوره (بدهکار)", "closing_debit_display", 98),
          Col("ماندهٔ پایان دوره (بستانکار)", "closing_credit_display", 102)],
         totals_row={2: "$P{totalOpeningDebitDisplay}", 3: "$P{totalOpeningCreditDisplay}", 4: "$P{totalPeriodDebitDisplay}",
                     5: "$P{totalPeriodCreditDisplay}", 6: "$P{totalClosingDebitDisplay}", 7: "$P{totalClosingCreditDisplay}"},
         totals_label_span=2),
    Spec("journal_book.jrxml", "journal_book_pro.jrxml", True, '"دفتر روزنامه"', "$P{companyName}",
         [("بازهٔ گزارش", "$P{dateRangeLabel}")],
         [Col("تاریخ", "document_date_display", 55), Col("شماره", "document_no_display", 45), Col("کد حساب", "account_code", 55),
          Col("نام حساب", "account_name", 90, "Right"), Col("تفصیلی", "detail_name", 70, "Right"),
          Col("مرکز هزینه", "cost_center_name", 55, "Right"), Col("پروژه", "project_name", 55, "Right"),
          Col("مرکز سود", "profit_center_name", 55, "Right"), Col("شرح", "description", 147, "Right"),
          Col("بدهکار", "debit_display", 87), Col("بستانکار", "credit_display", 88)],
         totals_row={9: "$P{totalDebitDisplay}", 10: "$P{totalCreditDisplay}"}, totals_label_span=9),
    Spec("account_ledger_detail.jrxml", "account_ledger_detail_pro.jrxml", True, '"دفتر کل / معین / تفصیلی"', "$P{companyName}",
         [("حساب", "$P{accountLabel}"), ("بازهٔ گزارش", "$P{dateRangeLabel}")],
         [Col("تاریخ", "date_display", 60), Col("شماره", "document_no_display", 45), Col("شرح", "description", 317, "Right"),
          Col("بدهکار", "debit_display", 90), Col("بستانکار", "credit_display", 90), Col("مانده", "balance_display", 90),
          Col("مبلغ ارزی", "fc_amount_display", 65), Col("ارز", "fc_currency_display", 45)],
         totals_row={3: "$P{totalDebitDisplay}", 4: "$P{totalCreditDisplay}"}, totals_label_span=3),
    Spec("income_statement.jrxml", "income_statement_pro.jrxml", False, '"صورت سود و زیان"', "$P{companyName}",
         [("بازهٔ گزارش", "$P{dateRangeLabel}")],
         [Col("کد", "account_code", 70), Col("نام حساب", "account_name", 200, "Right"), Col("دسته", "category_label", 80, "Right"),
          Col("دورهٔ جاری", "current_amount_display", 95), Col("سال قبل", "previous_amount_display", 94)],
         grand_total=("$P{netIncomeLabel}", "$P{netIncomeDisplay}")),
    Spec("balance_sheet.jrxml", "balance_sheet_pro.jrxml", False, '"ترازنامه"', "$P{companyName}",
         [("تاریخ", "$P{dateLabel}")],
         [Col("کد", "right_code", 40), Col("دارایی‌ها", "right_name", 150, "Right"), Col("مبلغ", "right_amount_display", 79),
          Col("کد", "left_code", 40), Col("بدهی‌ها و حقوق صاحبان سهام", "left_name", 151, "Right"),
          Col("مبلغ", "left_amount_display", 79)],
         notes=[("", "$P{totalRightLine}"), ("", "$P{totalLeftLine}"), ("", "$P{balanceNote}")]),
]


def main() -> None:
    for spec in SPECS:
        assert sum(c.width for c in spec.cols) == (802 if spec.landscape else 539), spec.out
        (TEMPLATES / spec.out).write_text(build(spec), encoding="utf-8")
        print("ok", spec.out)


if __name__ == "__main__":
    main()
