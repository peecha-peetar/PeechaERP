import { ApiClient, Fetcher } from "../src/api/client";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { LocalCache } from "../src/storage/localCache";
import { TokenStore } from "../src/storage/tokenStore";
import { OfflineQueue } from "../src/sync/offlineQueue";
import { SyncEngine } from "../src/sync/syncEngine";
import { VisitCorrelationStore } from "../src/sync/visitCorrelation";

function jsonResponse(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, statusText: String(status), json: async () => body } as unknown as Response;
}

/** رفعِ باگِ واقعیِ کشف‌شده: قبلاً COMPLETE_VISIT/SKIP_VISIT از
 * VisitDetailScreen مقدارِ visit_plan_id را به‌جایِ customer_visit_id
 * می‌فرستادند (چون شناسهٔ واقعی فقط بعدِ Syncِ موفقِ START_VISIT معلوم
 * می‌شود). این تست دقیقاً همان مسیر را (نه یک شبیه‌سازیِ ساده‌شده) از
 * طریقِ VisitCorrelationStore بازتولید می‌کند. */
describe("Visit lifecycle correlation (رفعِ باگِ customer_visit_id)", () => {
  async function buildEngine(fetcher: Fetcher) {
    const kv = new InMemoryKeyValueStore();
    const store = new TokenStore(kv);
    await store.setTokens("acc", "ref");
    const api = new ApiClient("http://api.local", store, fetcher);
    const queue = new OfflineQueue(kv);
    const cache = new LocalCache(kv);
    const correlation = new VisitCorrelationStore(kv);
    return { api, queue, cache, correlation, engine: new SyncEngine(api, queue, cache, correlation) };
  }

  it("COMPLETE_VISIT با startActionKey، شناسهٔ واقعیِ برگشته از START_VISIT را می‌فرستد (نه visit_plan_id)", async () => {
    const calls: { url: string }[] = [];
    const fetcher: Fetcher = jest.fn(async (url: string) => {
      calls.push({ url: String(url) });
      if (String(url).includes("/visits/start")) return jsonResponse(200, { customer_visit_id: 4242 });
      return jsonResponse(204, undefined);
    }) as unknown as Fetcher;
    const { engine, queue } = await buildEngine(fetcher);

    const startAction = await queue.enqueue({
      type: "START_VISIT",
      payload: { customer_detail_account_id: 10, visit_plan_id: 999, check_in_latitude: null, check_in_longitude: null },
    });
    await queue.enqueue({
      type: "COMPLETE_VISIT",
      payload: { startActionKey: startAction.idempotencyKey, notes: "خوب بود" },
    });

    const result = await engine.pushQueue();

    expect(result.succeeded).toHaveLength(2);
    const completeCall = calls.find((c) => c.url.includes("/visits/") && c.url.includes("/complete"));
    expect(completeCall?.url).toContain("/visits/4242/complete");
    expect(completeCall?.url).not.toContain("/visits/999/");
  });

  it("اگر START_VISیTِ مرتبط هنوز resolve نشده باشد، COMPLETE_VISIT به‌جایِ ارسالِ شناسهٔ غلط failedButKept می‌شود", async () => {
    const fetcher: Fetcher = jest.fn(async () => jsonResponse(204, undefined)) as unknown as Fetcher;
    const { engine, queue } = await buildEngine(fetcher);

    await queue.enqueue({
      type: "COMPLETE_VISIT",
      payload: { startActionKey: "start-key-that-never-resolved", notes: undefined },
    });

    const result = await engine.pushQueue();

    expect(result.succeeded).toHaveLength(0);
    expect(result.failedButKept).toHaveLength(1);
    expect(await queue.size()).toBe(0);
  });

  it("VisitCorrelationStore ماندگار است -- بعدِ حذفِ START_VISIT از صف هم جواب را نگه می‌دارد", async () => {
    const kv = new InMemoryKeyValueStore();
    const correlation = new VisitCorrelationStore(kv);
    await correlation.resolve("key-1", 777);
    expect(await correlation.get("key-1")).toBe(777);
    expect(await correlation.get("key-not-set")).toBeNull();
  });
});
