import { InvoicePrintData } from "../api/types";
import { formatJalaliDate } from "../jalali";
import { VAZIRMATN_BOLD_WOFF2_BASE64, VAZIRMATN_REGULAR_WOFF2_BASE64 } from "./vazirmatnFont";

const PERSIAN_DIGITS = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];

function fa(text: string | number): string {
  return String(text).replace(/[0-9]/g, (d) => PERSIAN_DIGITS[Number(d)]);
}

function escapeHtml(text: string | null | undefined): string {
  return (text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function money(value: string): string {
  const n = Number(value);
  if (Number.isNaN(n)) return escapeHtml(value);
  return fa(Math.round(n).toLocaleString("en-US")).replace(/,/g, "٬");
}

function qty(value: string): string {
  const n = Number(value);
  if (Number.isNaN(n)) return escapeHtml(value);
  return fa(String(Number(n.toFixed(3))));
}

/** صفحهٔ چاپِ فاکتور (A5، راست‌به‌چپ، فونتِ وزیرِ جاسازی‌شده، بدونِ آیکن).
 * همان داده‌ای که /orders/{id}/print-data برمی‌گرداند؛ برایِ فاکتوری که
 * هنوز همگام‌سازی نشده، همین ساختار از سبدِ محلی ساخته می‌شود و
 * document_no خالی است (برچسبِ «پیش‌نمایش» می‌خورد). */
export function buildInvoiceHtml(data: InvoicePrintData): string {
  const isInvoice = data.document_type_code === "SALES_INVOICE";
  const title = isInvoice ? "فاکتورِ فروش" : "سفارشِ فروش";
  const numberLabel = data.document_no !== null ? fa(data.document_no) : "پس از همگام‌سازی";
  const companyIds = [
    data.company.economic_code ? `کدِ اقتصادی: ${fa(escapeHtml(data.company.economic_code))}` : "",
    data.company.national_id ? `شناسهٔ ملی: ${fa(escapeHtml(data.company.national_id))}` : "",
  ].filter(Boolean).join(" · ");

  const lineRows = data.lines
    .map(
      (ln, index) => `
      <tr>
        <td class="c">${fa(index + 1)}</td>
        <td>${escapeHtml(ln.item_name ?? ln.item_code)}<div class="muted">${fa(escapeHtml(ln.item_code))}</div></td>
        <td class="c">${qty(ln.quantity)} ${escapeHtml(ln.uom_code)}</td>
        <td class="n">${money(ln.unit_price)}</td>
        <td class="n">${Number(ln.discount_amount) ? money(ln.discount_amount) : "—"}</td>
        <td class="n">${money(ln.line_total)}</td>
      </tr>`,
    )
    .join("");

  const settlementRows = data.settlement_lines
    .map(
      (s) => `<tr><td>${escapeHtml(s.label)}${s.note ? `<div class="muted">${escapeHtml(s.note)}</div>` : ""}</td><td class="n">${money(s.amount)}</td></tr>`,
    )
    .join("");
  const remaining = Number(data.remaining_amount);
  const checkRows = data.checks
    .map(
      (c) => `<tr><td>${fa(escapeHtml(c.check_no))}</td><td>${escapeHtml(c.bank_name)}</td><td class="c">${formatJalaliDate(c.due_date)}</td><td class="n">${money(c.amount)}</td></tr>`,
    )
    .join("");

  return `<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8" />
<style>
  @font-face { font-family: "Vazirmatn"; font-weight: 400; src: url(data:font/woff2;base64,${VAZIRMATN_REGULAR_WOFF2_BASE64}) format("woff2"); }
  @font-face { font-family: "Vazirmatn"; font-weight: 700; src: url(data:font/woff2;base64,${VAZIRMATN_BOLD_WOFF2_BASE64}) format("woff2"); }
  @page { size: A5; margin: 8mm; }
  * { box-sizing: border-box; }
  body { font-family: "Vazirmatn", sans-serif; direction: rtl; text-align: right; color: #111; font-size: 11px; margin: 0; }
  h1 { font-size: 16px; margin: 0 0 2px; }
  .head { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1.5px solid #111; padding-bottom: 6px; margin-bottom: 8px; }
  .muted { color: #666; font-size: 9.5px; }
  .box { border: 1px solid #bbb; border-radius: 4px; padding: 6px 8px; margin-bottom: 8px; }
  .row { display: flex; justify-content: space-between; gap: 8px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 8px; }
  th, td { border: 1px solid #bbb; padding: 4px 5px; vertical-align: top; }
  th { background: #f0f0f0; font-weight: 700; }
  td.n, th.n { text-align: left; direction: ltr; white-space: nowrap; }
  td.c { text-align: center; white-space: nowrap; }
  .totals td { font-weight: 700; }
  .grand td { font-size: 13px; background: #f0f0f0; }
  .preview { border: 1px dashed #999; padding: 4px; text-align: center; margin-bottom: 8px; }
  .sign { display: flex; justify-content: space-between; margin-top: 18px; }
  .sign div { width: 45%; border-top: 1px solid #999; padding-top: 4px; text-align: center; }
</style>
</head>
<body>
  <div class="head">
    <div>
      <h1>${escapeHtml(data.company.name)}</h1>
      ${companyIds ? `<div class="muted">${companyIds}</div>` : ""}
    </div>
    <div style="text-align:left">
      <h1>${title}</h1>
      <div>شماره: ${numberLabel}</div>
      <div>تاریخ: ${formatJalaliDate(data.document_date)}</div>
    </div>
  </div>
  ${data.document_no === null ? `<div class="preview">پیش‌نمایش -- این فاکتور هنوز همگام‌سازی نشده و شمارهٔ رسمی ندارد.</div>` : ""}
  <div class="box">
    <div class="row"><div>مشتری: <b>${escapeHtml(data.customer.name)}</b></div><div>${data.customer.code ? `کد: ${fa(escapeHtml(data.customer.code))}` : ""}</div></div>
    ${data.customer.phone || data.customer.address ? `<div class="muted">${fa(escapeHtml(data.customer.phone))} ${escapeHtml(data.customer.address)}</div>` : ""}
    ${data.seller_name ? `<div class="muted">فروشنده: ${escapeHtml(data.seller_name)}</div>` : ""}
  </div>
  <table>
    <thead><tr><th>ردیف</th><th>کالا</th><th>تعداد</th><th class="n">فی</th><th class="n">تخفیف</th><th class="n">مبلغ</th></tr></thead>
    <tbody>${lineRows}</tbody>
  </table>
  <table class="totals">
    <tr><td>جمعِ کل</td><td class="n">${money(data.gross_amount)}</td></tr>
    ${Number(data.discount_amount) ? `<tr><td>تخفیف</td><td class="n">${money(data.discount_amount)}</td></tr>` : ""}
    ${Number(data.tax_amount) ? `<tr><td>مالیات و عوارض</td><td class="n">${money(data.tax_amount)}</td></tr>` : ""}
    <tr class="grand"><td>مبلغِ قابلِ پرداخت</td><td class="n">${money(data.total_amount)}</td></tr>
  </table>
  ${isInvoice ? `
  <table>
    <thead><tr><th>نحوهٔ تسویه</th><th class="n">مبلغ</th></tr></thead>
    <tbody>
      ${settlementRows}
      <tr class="totals"><td>${remaining > 0 ? "مانده (نسیه)" : "مانده"}</td><td class="n">${money(data.remaining_amount)}</td></tr>
    </tbody>
  </table>
  ${checkRows ? `<table><thead><tr><th>شمارهٔ چک</th><th>بانک</th><th>سررسید</th><th class="n">مبلغ</th></tr></thead><tbody>${checkRows}</tbody></table>` : ""}` : ""}
  <div class="sign"><div>امضایِ فروشنده</div><div>امضایِ خریدار</div></div>
</body>
</html>`;
}
