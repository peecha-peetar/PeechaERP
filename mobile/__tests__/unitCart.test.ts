import { CatalogItem } from "../src/api/types";
import {
  baseQuantitiesByItem, buildLocalPrintData, Cart, cartKey, cartTotal, defaultSalesUnit, itemBaseQuantity, itemUnits,
  lineBaseQuantity, resolveScannedCode,
} from "../src/screens/invoice/cart";

const unit = (uom_id: number, code: string, name: string, factor: string, extra: Partial<NonNullable<CatalogItem["units"]>[number]> = {}) => ({
  uom_id, item_unit_id: uom_id, code, name, symbol: null, factor, is_base: factor === "1", is_default_sales: false,
  is_default_purchase: false, decimal_places: 0, allow_decimal: false, min_quantity: null, max_quantity: null, price: null,
  barcodes: [] as string[], ...extra,
});

const ITEM: CatalogItem = {
  item_id: 7, code: "DR-1", name: "نوشابه", barcode: "111", sku: null, category_id: null, brand_id: null,
  base_uom_id: 1, base_uom_code: "PCS", default_tax_percent: null, stock_quantity: "500", photo_base64: null,
  units: [
    unit(1, "PCS", "عدد", "1", { barcodes: ["111"], price: "10000" }),
    unit(2, "PACK", "بسته", "6", { barcodes: ["222"], price: "58000" }),
    unit(3, "CTN", "کارتن", "24", { barcodes: ["333"], is_default_sales: true, price: "230000" }),
  ],
};

const OLD_ITEM: CatalogItem = { ...ITEM, item_id: 8, barcode: "999", units: undefined };

describe("واحدِ فروش در سبد (R225)", () => {
  it("بارکدِ هر واحد کالا و واحدِ درست را برمی‌گرداند", () => {
    expect(resolveScannedCode([ITEM], "333")?.unit.code).toBe("CTN");
    expect(resolveScannedCode([ITEM], "222")?.unit.code).toBe("PACK");
    expect(resolveScannedCode([ITEM], "111")?.unit.code).toBe("PCS");
    expect(resolveScannedCode([ITEM], "404")).toBeNull();
  });

  it("کشِ قدیمی بدونِ units: فقط واحدِ پایه، بارکدِ کالا همچنان کار می‌کند", () => {
    expect(itemUnits(OLD_ITEM)).toHaveLength(1);
    const match = resolveScannedCode([OLD_ITEM], "999");
    expect(match?.unit.uom_id).toBe(1);
    expect(match?.unit.factor).toBe("1");
  });

  it("واحدِ پیش‌فرضِ فروش", () => {
    expect(defaultSalesUnit(ITEM).code).toBe("CTN");
    expect(defaultSalesUnit(OLD_ITEM).uom_id).toBe(1);
  });

  it("۲ کارتن + ۳ بسته + ۴ عدد = ۷۰ عدد؛ ردیف‌ها جدا و مبلغ به قیمتِ هر واحد", () => {
    const base = { item: ITEM, discountAmount: 0, taxPercent: 0 };
    const cart: Cart = {
      [cartKey(7, 3)]: { ...base, quantity: 2, unitPrice: 230000, uomId: 3, uomCode: "CTN", factor: 24 },
      [cartKey(7, 2)]: { ...base, quantity: 3, unitPrice: 58000, uomId: 2, uomCode: "PACK", factor: 6 },
      [cartKey(7, 1)]: { ...base, quantity: 4, unitPrice: 10000, uomId: 1, uomCode: "PCS", factor: 1 },
    };
    expect(lineBaseQuantity(cart[cartKey(7, 3)])).toBe(48);
    expect(itemBaseQuantity(cart, 7)).toBe(70);
    expect(itemBaseQuantity(cart, 7, cartKey(7, 1))).toBe(66);
    expect(baseQuantitiesByItem(cart)).toEqual({ 7: 70 });
    expect(cartTotal(cart)).toBe(2 * 230000 + 3 * 58000 + 4 * 10000);
    const print = buildLocalPrintData({
      companyName: "x", sellerName: "y", customer: { detail_account_id: 1, code: "C", name: "c" } as never,
      cart, settlementLines: [], methods: [],
    });
    expect(print.lines.map((l) => l.uom_code)).toEqual(["CTN", "PACK", "PCS"]);
  });
});
