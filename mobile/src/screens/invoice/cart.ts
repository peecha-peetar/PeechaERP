import { CatalogItem, CustomerRow, InvoicePrintData, OrderSettlementLineInput, SettlementMethodRow } from "../../api/types";
import { todayIsoDate } from "../../jalali";

export interface CartLine {
  item: CatalogItem;
  quantity: number;
  /** null یعنی قیمت هنوز از سرور گرفته نشده (آفلاین/بدونِ فهرستِ قیمت) --
   * ویزیتور باید پیش از ثبت آن را دستی وارد کند. */
  unitPrice: number | null;
  /** ویزیتور قیمت را دستی عوض کرده -- دیگر با قیمتِ سیستم بازنویسی نمی‌شود. */
  manualPrice?: boolean;
  /** طبقِ باگِ واقعیِ کشف‌شده (R210): تخفیفِ کلِ همین ردیف (به همین تعداد)
   * از GET /pricing/resolve -- قبلاً گرفته می‌شد ولی هیچ‌جا استفاده/ارسال
   * نمی‌شد. با قیمتِ دستیِ ویزیتور دیگر معنا ندارد و صفر می‌شود. */
  discountAmount: number;
  /** درصدِ مالیاتِ ارزش‌افزوده -- فقط برایِ پیش‌نمایشِ محلی؛ خودِ سرور
   * هنگامِ ثبتِ سند با همان اولویتِ دسکتاپ (شرکت→انبار→کالا) دوباره و
   * مستقلاً تعیین می‌کند. */
  taxPercent: number;
}

export type Cart = Record<number, CartLine>;

export function cartLines(cart: Cart): CartLine[] {
  return Object.values(cart).filter((l) => l.quantity > 0);
}

export function lineGrossAmount(line: CartLine): number {
  return line.quantity * (line.unitPrice ?? 0);
}

export function lineDiscountAmount(line: CartLine): number {
  return Math.min(line.discountAmount, lineGrossAmount(line));
}

export function lineNetAmount(line: CartLine): number {
  return lineGrossAmount(line) - lineDiscountAmount(line);
}

export function lineTaxAmount(line: CartLine): number {
  const net = lineNetAmount(line);
  return net > 0 && line.taxPercent > 0 ? (net * line.taxPercent) / 100 : 0;
}

/** مبلغِ نهاییِ همین ردیف (قیمت × تعداد − تخفیف + مالیات). */
export function lineTotalAmount(line: CartLine): number {
  return lineNetAmount(line) + lineTaxAmount(line);
}

function sumLines(cart: Cart, pick: (line: CartLine) => number): number {
  return cartLines(cart).reduce((sum, l) => sum + pick(l), 0);
}

export function cartGrossTotal(cart: Cart): number {
  return sumLines(cart, lineGrossAmount);
}

export function cartDiscountTotal(cart: Cart): number {
  return sumLines(cart, lineDiscountAmount);
}

export function cartTaxTotal(cart: Cart): number {
  return sumLines(cart, lineTaxAmount);
}

/** مبلغِ نهاییِ فاکتور (شاملِ تخفیف و مالیاتِ ارزش‌افزوده). */
export function cartTotal(cart: Cart): number {
  return sumLines(cart, lineTotalAmount);
}

export function missingPriceCount(cart: Cart): number {
  return cartLines(cart).filter((l) => l.unitPrice === null).length;
}

/** همان ساختارِ /orders/{id}/print-data، از داده‌یِ محلی -- برایِ چاپِ
 * پیش‌نمایشِ فاکتوری که هنوز همگام‌سازی نشده (document_no خالی). این
 * پیش‌نمایش با همان تخفیف/مالياتِ گرفته‌شده از GET /pricing/resolve و
 * default_tax_percentِ کالا محاسبه می‌شود؛ فاکتورِ رسمی هنوز پس از
 * همگام‌سازی از خودِ سرور چاپ می‌شود (ممکن است اگر شرکت/انبار درصدِ
 * مالياتِ دیگری override کرده باشند، اندکی فرق کند). */
export function buildLocalPrintData(params: {
  companyName: string;
  sellerName: string;
  customer: CustomerRow;
  cart: Cart;
  settlementLines: OrderSettlementLineInput[];
  methods: SettlementMethodRow[];
}): InvoicePrintData {
  const lines = cartLines(params.cart);
  const total = cartTotal(params.cart);
  const paid = params.settlementLines.reduce((sum, l) => sum + Number(l.amount), 0);
  const labels = Object.fromEntries(params.methods.map((m) => [m.method_code, m.label]));
  return {
    document_id: null,
    document_type_code: "SALES_INVOICE",
    document_no: null,
    document_date: todayIsoDate(),
    status_code: "PENDING_SYNC",
    company: { name: params.companyName, economic_code: null, national_id: null },
    seller_name: params.sellerName,
    customer: {
      detail_account_id: params.customer.detail_account_id,
      code: params.customer.code,
      name: params.customer.name,
      phone: null,
      address: null,
    },
    lines: lines.map((l, index) => ({
      line_no: index + 1,
      item_code: l.item.code,
      item_name: l.item.name,
      uom_code: l.item.base_uom_code,
      quantity: String(l.quantity),
      unit_price: String(l.unitPrice ?? 0),
      discount_amount: String(lineDiscountAmount(l)),
      tax_amount: String(lineTaxAmount(l)),
      line_total: String(lineTotalAmount(l)),
    })),
    gross_amount: String(cartGrossTotal(params.cart)),
    discount_amount: String(cartDiscountTotal(params.cart)),
    tax_amount: String(cartTaxTotal(params.cart)),
    total_amount: String(total),
    settlement_lines: params.settlementLines.map((l) => ({
      method_code: l.method_code,
      label: labels[l.method_code] ?? l.method_code,
      amount: l.amount,
      note: l.note ?? null,
    })),
    checks: params.settlementLines.flatMap((l) =>
      (l.checks ?? []).map((c) => ({ check_no: c.check_no, bank_name: c.check_bank_name ?? null, due_date: c.due_date, amount: c.amount })),
    ),
    settled_amount: String(paid),
    remaining_amount: String(Math.max(0, total - paid)),
  };
}
