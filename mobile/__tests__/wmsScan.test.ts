import { ApiClient, Fetcher } from "../src/api/client";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { LocalCache } from "../src/storage/localCache";
import { TokenStore } from "../src/storage/tokenStore";
import { OfflineQueue } from "../src/sync/offlineQueue";
import { SyncEngine } from "../src/sync/syncEngine";
import { submitWmsAction } from "../src/sync/wmsSubmit";

function jsonResponse(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, statusText: String(status), json: async () => body } as unknown as Response;
}

async function build(fetcher: Fetcher) {
  const kv = new InMemoryKeyValueStore();
  const store = new TokenStore(kv);
  await store.setTokens("acc", "ref");
  const api = new ApiClient("http://api.local", store, fetcher);
  const queue = new OfflineQueue(kv);
  return { api, queue, engine: new SyncEngine(api, queue, new LocalCache(kv)) };
}

describe("تایید عملیات انبار با اسکن (R304)", () => {
  it("متن اسکن‌شده همراه برداشت، جانمایی، تامین و انتقال به سرور می‌رود", async () => {
    const calls: { url: string; body: unknown }[] = [];
    const fetcher = jest.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, body: init.body ? JSON.parse(String(init.body)) : null });
      return jsonResponse(200, { status: "DONE", stock_document_id: 1 });
    }) as unknown as Fetcher;
    const { queue, engine } = await build(fetcher);
    await submitWmsAction(queue, engine, {
      type: "WMS_PICK", payload: { taskId: 4, quantity: "3", scans: { location: "PEECHA-LOC:5:WH01-B01", item: "6260000000011" } },
    });
    await submitWmsAction(queue, engine, { type: "WMS_PUTAWAY", payload: { taskId: 5, toLocationId: 9, scans: { location: "WH01-B09" } } });
    await submitWmsAction(queue, engine, { type: "WMS_REPLENISH", payload: { taskId: 6, quantity: null, scans: { from: "A", to: "B" } } });
    await submitWmsAction(queue, engine, {
      type: "WMS_TRANSFER",
      payload: { item_id: 1, from_location_id: 2, to_location_id: 3, quantity: "5", scanned_from: "A", scanned_to: "B", scanned_item: "X" },
    });
    expect(calls.map((c) => c.body)).toEqual([
      { quantity: "3", scanned_location: "PEECHA-LOC:5:WH01-B01", scanned_item: "6260000000011" },
      { to_location_id: 9, scanned_location: "WH01-B09" },
      { quantity: null, scanned_from: "A", scanned_to: "B" },
      { item_id: 1, from_location_id: 2, to_location_id: 3, quantity: "5", scanned_from: "A", scanned_to: "B", scanned_item: "X" },
    ]);
  });

  it("اقدام قدیمی صف (بدون اسکن) هم ارسال می‌شود", async () => {
    const bodies: unknown[] = [];
    const fetcher = jest.fn(async (_url: string, init: RequestInit) => {
      bodies.push(JSON.parse(String(init.body)));
      return jsonResponse(200, { status: "DONE" });
    }) as unknown as Fetcher;
    const { queue, engine } = await build(fetcher);
    await submitWmsAction(queue, engine, { type: "WMS_PICK", payload: { taskId: 4, quantity: "3" } });
    expect(bodies).toEqual([{ quantity: "3", scanned_location: null, scanned_item: null }]);
  });

  it("تنظیمات انبار از سرور خوانده می‌شود", async () => {
    const fetcher = jest.fn(async () => jsonResponse(200, { scan_confirmation: true })) as unknown as Fetcher;
    const { api } = await build(fetcher);
    expect(await api.getWmsSettings()).toEqual({ scan_confirmation: true });
  });
});
