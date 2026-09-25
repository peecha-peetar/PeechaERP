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
}

export type Cart = Record<number, CartLine>;

export function cartLines(cart: Cart): CartLine[] {
  return Object.values(cart).filter((l) => l.quantity > 0);
}

export function cartTotal(cart: Cart): number {
  return cartLines(cart).reduce((sum, l) => sum + l.quantity * (l.unitPrice ?? 0), 0);
}

export function missingPriceCount(cart: Cart): number {
  return cartLines(cart).filter((l) => l.unitPrice === null).length;
}

/** همان ساختارِ /orders/{id}/print-data، از داده‌یِ محلی -- برایِ چاپِ
 * پیش‌نمایشِ فاکتوری که هنوز همگام‌سازی نشده (document_no خالی). مالیات
 * و تخفیفِ سمتِ سرور این‌جا معلوم نیست؛ فاکتورِ رسمی پس از همگام‌سازی
 * از خودِ سرور چاپ می‌شود. */
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
      discount_amount: "0",
      tax_amount: "0",
      line_total: String(l.quantity * (l.unitPrice ?? 0)),
    })),
    gross_amount: String(total),
    discount_amount: "0",
    tax_amount: "0",
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
