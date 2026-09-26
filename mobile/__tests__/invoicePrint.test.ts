import { buildInvoiceHtml } from "../src/print/invoiceHtml";
import { InvoicePrintData } from "../src/api/types";

/** طبقِ گزارشِ کاربر («چاپِ فاکتور و PDF کار نمی‌کند»): این تست
 * buildInvoiceHtml را با هر دو شکلِ دادهٔ واقعی -- پاسخِ سرور
 * (/orders/{id}/print-data) و پیش‌نمایشِ محلیِ ساخته‌شده در
 * screens/invoice/cart.ts پیش از همگام‌سازی -- اجرا می‌کند تا اگر
 * جایی یک فیلدِ undefined/null باعثِ کرشِ خاموش (که فقط به‌صورتِ
 * توستِ عمومیِ «چاپ انجام نشد» دیده می‌شود) بشود، همین‌جا آشکار شود. */

const serverInvoice: InvoicePrintData = {
  document_id: 42,
  document_type_code: "SALES_INVOICE",
  document_no: 1007,
  document_date: "2026-01-15",
  status_code: "POSTED",
  company: { name: "شرکتِ آزمایشی", economic_code: "12345", national_id: "6789" },
  seller_name: "علی رضایی",
  customer: { detail_account_id: 5, code: "C-1", name: "فروشگاهِ نمونه", phone: "09120000000", address: "تهران" },
  lines: [
    {
      line_no: 1, item_code: "9101", item_name: "کالایِ عادی", uom_code: "PCS",
      quantity: "3", unit_price: "10000", discount_amount: "0", tax_amount: "0", line_total: "30000",
    },
  ],
  gross_amount: "30000",
  discount_amount: "0",
  tax_amount: "0",
  total_amount: "30000",
  settlement_lines: [
    { method_code: "CASH", label: "نقد", amount: "10000", note: null },
    { method_code: "CHECK", label: "چک", amount: "13000", note: null },
  ],
  checks: [
    { check_no: "111", bank_name: "بانکِ ملی", due_date: "2026-02-01", amount: "13000" },
  ],
  settled_amount: "23000",
  remaining_amount: "7000",
};

const localPreview: InvoicePrintData = {
  document_id: null,
  document_type_code: "SALES_INVOICE",
  document_no: null,
  document_date: "2026-01-15",
  status_code: "PENDING_SYNC",
  company: { name: "شرکتِ آزمایشی", economic_code: null, national_id: null },
  seller_name: "علی رضایی",
  customer: { detail_account_id: 5, code: "C-1", name: "فروشگاهِ نمونه", phone: null, address: null },
  lines: [
    {
      line_no: 1, item_code: "9101", item_name: "کالایِ عادی", uom_code: "PCS",
      quantity: "3", unit_price: "10000", discount_amount: "0", tax_amount: "0", line_total: "30000",
    },
  ],
  gross_amount: "30000",
  discount_amount: "0",
  tax_amount: "0",
  total_amount: "30000",
  settlement_lines: [{ method_code: "CASH", label: "نقد", amount: "30000", note: null }],
  checks: [],
  settled_amount: "30000",
  remaining_amount: "0",
};

const preSalesOrder: InvoicePrintData = {
  ...localPreview,
  document_type_code: "SALES_ORDER",
  settlement_lines: [],
  checks: [],
};

describe("buildInvoiceHtml", () => {
  it("renders a server-synced invoice with checks/settlements without throwing", () => {
    const html = buildInvoiceHtml(serverInvoice);
    expect(html).toContain("فاکتورِ فروش");
    expect(html).toContain("فروشگاهِ نمونه");
    expect(html).toContain("بانکِ ملی");
  });

  it("renders a locally-built pre-sync preview without throwing", () => {
    const html = buildInvoiceHtml(localPreview);
    expect(html).toContain("پیش‌نمایش");
  });

  it("renders a SALES_ORDER (pre-sales, no settlement table) without throwing", () => {
    const html = buildInvoiceHtml(preSalesOrder);
    expect(html).toContain("سفارشِ فروش");
  });

  it("does not crash when checks/settlement_lines are empty arrays", () => {
    expect(() => buildInvoiceHtml({ ...serverInvoice, checks: [], settlement_lines: [] })).not.toThrow();
  });
});
