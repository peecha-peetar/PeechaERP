import { BankRow, CatalogResponse } from "../api/types";
import { KeyValueStore } from "./keyValueStore";

const CATALOG_KEY_PREFIX = "peecha.catalog_cache.";
const BANKS_KEY = "peecha.banks_cache";

function catalogKey(warehouseId: number | null): string {
  return CATALOG_KEY_PREFIX + (warehouseId ?? "none");
}

/** آخرین کاتالوگِ موفق (به‌تفکیکِ انبار) و فهرستِ بانک‌ها -- تا فاکتورِ
 * پخشِ گرم در نبودِ اینترنت هم کار کند. پس از هر فروشِ ثبت‌شده، موجودیِ
 * همین کشِ محلی کم می‌شود تا فروش‌هایِ آفلاینِ پشتِ‌سرِهم از موجودیِ
 * واقعیِ خودرو بیشتر نشوند (انبارِ خودرو معمولاً موجودیِ منفی نمی‌پذیرد
 * و سرور چنین فاکتوری را پس از همگام‌سازی رد می‌کرد). */
export class CatalogCache {
  constructor(private readonly kv: KeyValueStore) {}

  async saveCatalog(warehouseId: number | null, data: CatalogResponse): Promise<void> {
    await this.kv.setItem(catalogKey(warehouseId), JSON.stringify(data));
  }

  async getCatalog(warehouseId: number | null): Promise<CatalogResponse | null> {
    const raw = await this.kv.getItem(catalogKey(warehouseId));
    return raw === null ? null : (JSON.parse(raw) as CatalogResponse);
  }

  async deductStock(warehouseId: number | null, quantities: Record<number, number>): Promise<CatalogResponse | null> {
    const cached = await this.getCatalog(warehouseId);
    if (cached === null) return null;
    const updated: CatalogResponse = {
      ...cached,
      items: cached.items.map((item) =>
        item.stock_quantity !== null && quantities[item.item_id]
          ? { ...item, stock_quantity: String(Math.max(0, Number(item.stock_quantity) - quantities[item.item_id])) }
          : item,
      ),
    };
    await this.saveCatalog(warehouseId, updated);
    return updated;
  }

  async saveBanks(banks: BankRow[]): Promise<void> {
    await this.kv.setItem(BANKS_KEY, JSON.stringify(banks));
  }

  async getBanks(): Promise<BankRow[]> {
    const raw = await this.kv.getItem(BANKS_KEY);
    return raw === null ? [] : (JSON.parse(raw) as BankRow[]);
  }
}
