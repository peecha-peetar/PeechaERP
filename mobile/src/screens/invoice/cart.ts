import { CatalogItem, CatalogUnit, CustomerRow, InvoicePrintData, OrderSettlementLineInput, SettlementMethodRow } from "../../api/types";
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
  /** واحدِ همین ردیف (R225) -- خالی یعنی واحدِ پایهٔ کالا (سبدهایِ قدیمی). */
  uomId?: number;
  uomCode?: string;
  uomName?: string;
  /** ضریبِ تبدیل به واحدِ پایه (کارتنِ ۲۴تایی = 24). */
  factor?: number;
}

/** کلید = کالا + واحد، تا «۲ کارتن + ۳ عدد» از یک کالا دو ردیفِ جدا باشد. */
export type Cart = Record<string, CartLine>;

export function cartKey(itemId: number, uomId: number): string {
  return `${itemId}:${uomId}`;
}

export function lineUomId(line: CartLine): number {
  return line.uomId ?? line.item.base_uom_id;
}

export function lineKey(line: CartLine): string {
  return cartKey(line.item.item_id, lineUomId(line));
}

/** مقدارِ ردیف به واحدِ پایه (برایِ کنترل و کسرِ موجودی). */
export function lineBaseQuantity(line: CartLine): number {
  return line.quantity * (line.factor ?? 1);
}

/** واحدهایِ قابلِ‌فروشِ کالا؛ اگر سرور/کشِ قدیمی units نفرستاده، فقط واحدِ پایه. */
export function itemUnits(item: CatalogItem): CatalogUnit[] {
  if (item.units && item.units.length > 0) return item.units;
  return [{
    uom_id: item.base_uom_id, item_unit_id: null, code: item.base_uom_code, name: item.base_uom_code, symbol: null,
    factor: "1", is_base: true, is_default_sales: true, is_default_purchase: true, decimal_places: 0, allow_decimal: false,
    min_quantity: null, max_quantity: null, price: null, barcodes: item.barcode ? [item.barcode] : [],
  }];
}

export function defaultSalesUnit(item: CatalogItem): CatalogUnit {
  const units = itemUnits(item);
  return units.find((u) => u.is_default_sales) ?? units.find((u) => u.is_base) ?? units[0];
}

export function unitLabel(unit: CatalogUnit): string {
  return unit.is_base ? unit.name : `${unit.name} (${Number(unit.factor)})`;
}

/** جمعِ مقدارِ پایهٔ همهٔ ردیف‌هایِ یک کالا (همهٔ واحدها). */
export function itemBaseQuantity(cart: Cart, itemId: number, exceptKey?: string): number {
  return Object.entries(cart)
    .filter(([key, l]) => l.item.item_id === itemId && key !== exceptKey)
    .reduce((sum, [, l]) => sum + lineBaseQuantity(l), 0);
}

/** مقدارِ کسرِ موجودیِ کش به تفکیکِ کالا و به واحدِ پایه. */
export function baseQuantitiesByItem(cart: Cart): Record<number, number> {
  const out: Record<number, number> = {};
  for (const l of cartLines(cart)) out[l.item.item_id] = (out[l.item.item_id] ?? 0) + lineBaseQuantity(l);
  return out;
}

/** بارکد → کالا + واحد (بارکدِ هر واحد اول؛ بعد بارکد/SKU/کدِ کالا با واحدِ پایه). */
export function resolveScannedCode(items: CatalogItem[], code: string): { item: CatalogItem; unit: CatalogUnit } | null {
  const needle = code.trim();
  if (!needle) return null;
  for (const item of items) {
    const unit = (item.units ?? []).find((u) => u.barcodes.includes(needle));
    if (unit) return { item, unit };
  }
  const item =
    items.find((i) => i.barcode === needle) ?? items.find((i) => i.sku === needle) ?? items.find((i) => i.code === needle);
  if (!item) return null;
  const units = itemUnits(item);
  return { item, unit: units.find((u) => u.is_base) ?? units[0] };
}

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
      uom_code: l.uomCode ?? l.item.base_uom_code,
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
