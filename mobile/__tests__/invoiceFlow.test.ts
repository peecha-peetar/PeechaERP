import { ApiClient, Fetcher } from "../src/api/client";
import { CatalogResponse, InvoicePrintData } from "../src/api/types";
import { parseAmount, toAsciiDigits } from "../src/format";
import { parseJalaliDate } from "../src/jalali";
import { buildInvoiceHtml } from "../src/print/invoiceHtml";
import { buildLocalPrintData, cartTotal, missingPriceCount } from "../src/screens/invoice/cart";
import { CatalogCache } from "../src/storage/catalogCache";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { LocalCache } from "../src/storage/localCache";
import { TokenStore } from "../src/storage/tokenStore";
import { InvoiceResultStore } from "../src/sync/invoiceResults";
import { OfflineQueue } from "../src/sync/offlineQueue";
import { VisitCorrelationStore } from "../src/sync/visitCorrelation";
import { SyncEngine } from "../src/sync/syncEngine";

function jsonResponse(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, statusText: String(status), json: async () => body } as unknown as Response;
}

const ITEM = {
  item_id: 1, code: "9101", name: "آب‌معدنی", barcode: "626", sku: null, category_id: null, brand_id: null,
  base_uom_id: 1, base_uom_code: "PCS", default_tax_percent: null, stock_quantity: "10",
};

const PRINT: InvoicePrintData = {
  document_id: 4, document_type_code: "SALES_INVOICE", document_no: 123, document_date: "2026-09-25", status_code: "POSTED",
  company: { name: "شرکتِ <نمونه>", economic_code: "411", national_id: null },
  seller_name: "صفایی",
  customer: { detail_account_id: 5, code: "C-1", name: "فروشگاه & شرکا", phone: null, address: null },
  lines: [{ line_no: 1, item_code: "9101", item_name: "آب‌معدنی", uom_code: "PCS", quantity: "3.000000", unit_price: "10000", discount_amount: "0", tax_amount: "0", line_total: "30000" }],
  gross_amount: "30000", discount_amount: "0", tax_amount: "0", total_amount: "30000",
  settlement_lines: [{ method_code: "CHECK", label: "چک", amount: "15000", note: null }],
  checks: [{ check_no: "123456", bank_name: "ملت", due_date: "2026-11-01", amount: "15000" }],
  settled_amount: "15000", remaining_amount: "15000",
};

describe("چاپِ فاکتور", () => {
  it("متن‌ها escape می‌شوند، ارقام فارسی و تاریخ شمسی است، نسیه و چک نمایش داده می‌شود", () => {
    const html = buildInvoiceHtml(PRINT);
    expect(html).toContain("شرکتِ &lt;نمونه&gt;");
    expect(html).toContain("فروشگاه &amp; شرکا");
    expect(html).not.toContain("<نمونه>");
    expect(html).toContain("شماره: ۱۲۳");
    expect(html).toContain("۱۴۰۵/۰۷/۰۳");
    expect(html).toContain("۳۰٬۰۰۰");
    expect(html).toContain("مانده (نسیه)");
    expect(html).toContain("۱۴۰۵/۰۸/۱۰");
    expect(html).toContain('dir="rtl"');
    expect(html).toContain('font-family: "Vazirmatn"');
    expect(html).not.toContain("پیش‌نمایش --");
  });

  it("فاکتورِ همگام‌نشده برچسبِ پیش‌نمایش دارد و شماره ندارد", () => {
    const html = buildInvoiceHtml({ ...PRINT, document_no: null });
    expect(html).toContain("پیش‌نمایش --");
    expect(html).toContain("پس از همگام‌سازی");
  });
});

describe("ورودی‌هایِ فارسی", () => {
  it("ارقامِ فارسی/عربی و جداکننده‌ها تبدیل می‌شوند", () => {
    expect(toAsciiDigits("۱۲٬۳۴۵")).toBe("12345");
    expect(toAsciiDigits("٤٥٦")).toBe("456");
    expect(parseAmount("۱۵۰۰۰")).toBe(15000);
    expect(parseAmount("abc")).toBe(0);
  });

  it("تاریخِ سررسیدِ شمسی به ISO تبدیل می‌شود و تاریخِ نامعتبر رد می‌شود", () => {
    expect(parseJalaliDate("۱۴۰۵/۰۸/۱۵")).toBe("2026-11-06");
    expect(parseJalaliDate("1405-8-15")).toBe("2026-11-06");
    expect(parseJalaliDate("1405/13/01")).toBeNull();
    expect(parseJalaliDate("1405/12/31")).toBeNull();
    expect(parseJalaliDate("")).toBeNull();
  });
});

describe("سبد و پیش‌نمایشِ محلی", () => {
  it("جمع، اقلامِ بی‌قیمت و ماندهٔ نسیه درست است", () => {
    const cart = { 1: { item: ITEM, quantity: 3, unitPrice: 10000 }, 2: { item: { ...ITEM, item_id: 2 }, quantity: 1, unitPrice: null } };
    expect(cartTotal(cart)).toBe(30000);
    expect(missingPriceCount(cart)).toBe(1);
    const data = buildLocalPrintData({
      companyName: "شرکت", sellerName: "صفایی", customer: { detail_account_id: 5, code: "C-1", name: "مشتری", gps_latitude: null, gps_longitude: null },
      cart: { 1: cart[1] }, settlementLines: [{ method_code: "CASH", amount: "10000" }], methods: [{ method_code: "CASH", label: "نقدی" }],
    });
    expect(data.document_no).toBeNull();
    expect(data.remaining_amount).toBe("20000");
    expect(data.settlement_lines[0].label).toBe("نقدی");
  });
});

describe("کشِ کاتالوگ", () => {
  it("پس از فروشِ آفلاین موجودیِ محلیِ خودرو کم می‌شود و منفی نمی‌شود", async () => {
    const cache = new CatalogCache(new InMemoryKeyValueStore());
    const catalog: CatalogResponse = { items: [ITEM, { ...ITEM, item_id: 2, stock_quantity: null }], categories: [], brands: [] };
    await cache.saveCatalog(7, catalog);
    const updated = await cache.deductStock(7, { 1: 4, 2: 1 });
    expect(updated!.items[0].stock_quantity).toBe("6");
    expect(updated!.items[1].stock_quantity).toBeNull();
    const again = await cache.deductStock(7, { 1: 99 });
    expect(again!.items[0].stock_quantity).toBe("0");
    expect(await cache.getCatalog(8)).toBeNull();
  });
});

describe("SyncEngine و فاکتورِ پخشِ گرم", () => {
  async function build(fetcher: Fetcher) {
    const kv = new InMemoryKeyValueStore();
    const tokens = new TokenStore(kv);
    await tokens.setTokens("acc", "ref");
    const api = new ApiClient("http://api.local", tokens, fetcher);
    const queue = new OfflineQueue(kv);
    const results = new InvoiceResultStore(kv);
    const engine = new SyncEngine(api, queue, new LocalCache(kv), new VisitCorrelationStore(kv), results);
    return { queue, results, engine };
  }
  const ORDER = {
    document_type_code: "SALES_INVOICE" as const, counterparty_detail_account_id: 5, warehouse_id: 1, channel_code: "VAN-1",
    currency_id: 1, lines: [{ item_id: 1, uom_id: 1, quantity: "1", unit_price: "1000" }], post_immediately: true,
  };

  it("شماره و هشدارِ تسویهٔ سرور برایِ صفحهٔ چاپ ذخیره می‌شود", async () => {
    const fetcher = jest.fn(async (url: any) => {
      if (String(url).endsWith("/orders")) return jsonResponse(200, { document_id: 42, line_ids: [7], document_no: 15, settlement_warning: "بدونِ سندِ دریافت" });
      return jsonResponse(200, { delivery_confirmation_id: 1 });
    }) as unknown as Fetcher;
    const { queue, results, engine } = await build(fetcher);
    const action = await queue.enqueue({ type: "CREATE_VAN_SALE_DELIVERY", payload: { order: ORDER, delivery: { notes: null } } });
    await engine.pushQueue();
    expect(await results.get(action.idempotencyKey)).toEqual({ documentId: 42, documentNo: 15, settlementWarning: "بدونِ سندِ دریافت" });
  });

  it("دو فراخوانِ هم‌زمانِ pushQueue فاکتور را دوبار نمی‌فرستند", async () => {
    let orderCalls = 0;
    const fetcher = jest.fn(async (url: any) => {
      if (String(url).endsWith("/orders")) {
        orderCalls += 1;
        await new Promise((r) => setTimeout(r, 10));
        return jsonResponse(200, { document_id: 42, line_ids: [7], document_no: 15 });
      }
      return jsonResponse(200, { delivery_confirmation_id: 1 });
    }) as unknown as Fetcher;
    const { queue, engine } = await build(fetcher);
    await queue.enqueue({ type: "CREATE_VAN_SALE_DELIVERY", payload: { order: ORDER, delivery: { notes: null } } });
    const [a, b] = await Promise.all([engine.pushQueue(), engine.pushQueue()]);
    expect(orderCalls).toBe(1);
    expect(a).toBe(b);
    expect(await queue.size()).toBe(0);
  });
});
