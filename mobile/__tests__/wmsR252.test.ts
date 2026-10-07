import { ApiClient, Fetcher } from "../src/api/client";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { LocalCache } from "../src/storage/localCache";
import { TokenStore } from "../src/storage/tokenStore";
import { OfflineQueue } from "../src/sync/offlineQueue";
import { SyncEngine } from "../src/sync/syncEngine";
import { submitWmsAction } from "../src/sync/wmsSubmit";

async function build(calls: { url: string; method: string; body: unknown }[]) {
  const fetcher = jest.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, method: String(init.method), body: init.body ? JSON.parse(String(init.body)) : undefined });
    return { ok: true, status: 200, statusText: "200", json: async () => ({ session_id: 9, task_ids: [1, 2], line_id: 3 }) } as unknown as Response;
  }) as unknown as Fetcher;
  const kv = new InMemoryKeyValueStore();
  const store = new TokenStore(kv);
  await store.setTokens("a", "r");
  const api = new ApiClient("http://api.local", store, fetcher);
  const queue = new OfflineQueue(kv);
  return { api, queue, engine: new SyncEngine(api, queue, new LocalCache(kv)) };
}

describe("R252: شمارش سریال، شروع شمارش، جانمایی و برچسب گروهی", () => {
  it("سریال‌های اسکن‌شده از صف به سرور می‌روند", async () => {
    const calls: { url: string; method: string; body: unknown }[] = [];
    const { queue, engine } = await build(calls);
    const outcome = await submitWmsAction(queue, engine, {
      type: "WMS_SERIAL_COUNT", payload: { sessionId: 4, locationId: 5, itemId: 6, serialNos: ["S1", "S2"] },
    });
    expect(outcome).toEqual({ status: "DONE" });
    expect(calls).toEqual([{ url: "http://api.local/locations/counts/4/serials", method: "POST",
      body: { location_id: 5, item_id: 6, serial_nos: ["S1", "S2"] } }]);
  });

  it("مسیرهای شروع شمارش، رسیدهای جانمایی و برچسب زیرمحل‌ها", async () => {
    const calls: { url: string; method: string; body: unknown }[] = [];
    const { api } = await build(calls);
    await api.createLocationCount(2, [7]);
    await api.listPutawaySources();
    await api.generatePutawayTasks(11);
    await api.getLocationLabels(7);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "POST http://api.local/locations/counts",
      "GET http://api.local/locations/putaway-sources",
      "POST http://api.local/locations/tasks/generate",
      "GET http://api.local/locations/7/labels",
    ]);
    expect(calls[0].body).toEqual({ warehouse_id: 2, location_ids: [7], blind: true });
    expect(calls[2].body).toEqual({ document_id: 11, task_type: "PUTAWAY" });
  });
});
