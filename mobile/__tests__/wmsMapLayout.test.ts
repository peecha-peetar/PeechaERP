import { WarehouseMapNode } from "../src/api/types";
import { ApiClient, Fetcher } from "../src/api/client";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { LocalCache } from "../src/storage/localCache";
import { TokenStore } from "../src/storage/tokenStore";
import { OfflineQueue } from "../src/sync/offlineQueue";
import { SyncEngine } from "../src/sync/syncEngine";
import { submitWmsAction } from "../src/sync/wmsSubmit";
import { layoutWarehouseMap, occupancyTone } from "../src/wms/mapLayout";

const node = (id: number, level: string, x: number, y: number, w: number, h: number, rotation = 0, occ: string | null = null): WarehouseMapNode => ({
  location_id: id, parent_id: null, code: `C${id}`, level, name: null, status: "ACTIVE", occupancy_percent: occ, quantity: "0",
  map: { x, y, width: w, height: h, rotation, z: null },
});

describe("نقشهٔ انبار موبایل (R250)", () => {
  it("مقیاس به عرض صفحه و جابه‌جایی مبدا", () => {
    const { rects, height } = layoutWarehouseMap([node(1, "AREA", 100, 50, 400, 200), node(2, "RACK", 150, 100, 40, 100, 0, "60")], 200);
    expect(rects.map((r) => r.locationId)).toEqual([1, 2]);
    expect(rects[0]).toMatchObject({ left: 0, top: 0, width: 200, height: 100 });
    expect(rects[1]).toMatchObject({ left: 25, top: 25, width: 20, height: 50, occupancy: 60 });
    expect(height).toBe(100);
  });

  it("چرخش ۹۰ درجه ابعاد را جابه‌جا می‌کند و طبقه/بی‌مختصات رسم نمی‌شوند", () => {
    const shelf: WarehouseMapNode = { ...node(3, "SHELF", 0, 0, 10, 10) };
    const noMap: WarehouseMapNode = { ...node(4, "BIN", 0, 0, 1, 1), map: null };
    const { rects } = layoutWarehouseMap([node(1, "RACK", 0, 0, 40, 200, 90), shelf, noMap], 200);
    expect(rects).toHaveLength(1);
    expect(rects[0]).toMatchObject({ width: 200, height: 40 });
  });

  it("رنگ اشغال", () => {
    expect([null, 0, 10, 60, 80, 95].map((v) => occupancyTone(v))).toEqual(["empty", "empty", "low", "mid", "high", "full"]);
  });

  it("ثبت شمارش محل از صف آفلاین", async () => {
    const calls: { url: string; body: unknown }[] = [];
    const fetcher = jest.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, body: JSON.parse(String(init.body)) });
      return { ok: true, status: 200, statusText: "200", json: async () => ({ line_id: 1 }) } as unknown as Response;
    }) as unknown as Fetcher;
    const kv = new InMemoryKeyValueStore();
    const store = new TokenStore(kv);
    await store.setTokens("a", "r");
    const api = new ApiClient("http://api.local", store, fetcher);
    const queue = new OfflineQueue(kv);
    const outcome = await submitWmsAction(queue, new SyncEngine(api, queue, new LocalCache(kv)), {
      type: "WMS_COUNT", payload: { sessionId: 3, locationId: 7, itemId: 9, quantity: "12" },
    });
    expect(outcome).toEqual({ status: "DONE" });
    expect(calls).toEqual([{ url: "http://api.local/locations/counts/3/record", body: { location_id: 7, item_id: 9, quantity: "12" } }]);
  });
});
