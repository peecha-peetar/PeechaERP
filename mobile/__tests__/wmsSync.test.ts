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

describe("عملیاتِ انبار (R249)", () => {
  it("انتقال با کلیدِ Idempotency به /locations/transfer می‌رود و از صف حذف می‌شود", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    const fetcher = jest.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return jsonResponse(200, { stock_document_id: 7 });
    }) as unknown as Fetcher;
    const { queue, engine } = await build(fetcher);
    const outcome = await submitWmsAction(queue, engine, {
      type: "WMS_TRANSFER",
      payload: { item_id: 1, from_location_id: 2, to_location_id: 3, quantity: "5" },
    });
    expect(outcome).toEqual({ status: "DONE" });
    expect(calls[0].url).toBe("http://api.local/locations/transfer");
    expect((calls[0].init.headers as Record<string, string>)["Idempotency-Key"]).toBeTruthy();
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ item_id: 1, from_location_id: 2, to_location_id: 3, quantity: "5" });
    expect(await queue.size()).toBe(0);
  });

  it("ردِ سرور (۴۰۰) با پیامِ فارسی برمی‌گردد و در صف نمی‌ماند", async () => {
    const fetcher = jest.fn(async () => jsonResponse(400, { detail: "محلِ مقصد مسدود است." })) as unknown as Fetcher;
    const { queue, engine } = await build(fetcher);
    const outcome = await submitWmsAction(queue, engine, { type: "WMS_PUTAWAY", payload: { taskId: 4, toLocationId: 9 } });
    expect(outcome).toEqual({ status: "REJECTED", reason: "محلِ مقصد مسدود است." });
    expect(await queue.size()).toBe(0);
  });

  it("بی‌اینترنت: اقدام در صف می‌ماند و بعداً به مسیرِ درست می‌رود", async () => {
    let online = false;
    const urls: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      if (!online) throw new TypeError("Network request failed");
      urls.push(url);
      return jsonResponse(200, { task_id: 4, status: "DONE" });
    }) as unknown as Fetcher;
    const { queue, engine } = await build(fetcher);
    const outcome = await submitWmsAction(queue, engine, { type: "WMS_PICK", payload: { taskId: 4, quantity: "3" } });
    expect(outcome).toEqual({ status: "QUEUED" });
    expect(await queue.size()).toBe(1);
    online = true;
    await submitWmsAction(queue, engine, { type: "WMS_REPLENISH", payload: { taskId: 5, quantity: null } });
    expect(urls).toEqual(["http://api.local/locations/tasks/4/pick", "http://api.local/locations/tasks/5/replenish"]);
    expect(await queue.size()).toBe(0);
  });

  it("کلاینت: جستجو و اسکنِ محل با پارامترِ کدشده", async () => {
    const urls: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      urls.push(url);
      return jsonResponse(200, { kind: "NONE", item_ids: [], locations: [] });
    }) as unknown as Fetcher;
    const { api } = await build(fetcher);
    await api.searchLocations("WH01-Z01");
    await api.scanLocation("PEECHA-LOC:5:WH01-Z01");
    await api.listWmsTasks("PICK");
    expect(urls).toEqual([
      "http://api.local/locations/search?q=WH01-Z01",
      "http://api.local/locations/scan?payload=PEECHA-LOC%3A5%3AWH01-Z01",
      "http://api.local/locations/tasks?task_type=PICK",
    ]);
  });
});
