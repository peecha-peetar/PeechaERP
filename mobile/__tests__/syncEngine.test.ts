import { ApiClient, ApiError, Fetcher } from "../src/api/client";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { LocalCache } from "../src/storage/localCache";
import { TokenStore } from "../src/storage/tokenStore";
import { OfflineQueue } from "../src/sync/offlineQueue";
import { SyncEngine } from "../src/sync/syncEngine";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  } as unknown as Response;
}

async function buildEngine(fetcher: Fetcher) {
  const kv = new InMemoryKeyValueStore();
  const store = new TokenStore(kv);
  await store.setTokens("acc", "ref");
  const api = new ApiClient("http://api.local", store, fetcher);
  const queue = new OfflineQueue(kv);
  const cache = new LocalCache(kv);
  return { api, queue, cache, engine: new SyncEngine(api, queue, cache) };
}

describe("SyncEngine", () => {
  it("pull خروجیِ سرور را کامل جایگزینِ کشِ محلی می‌کند", async () => {
    const fetcher: Fetcher = jest.fn(async () =>
      jsonResponse(200, { visit_plans: [{ visit_plan_id: 1, customer_detail_account_id: 5, visit_day_of_week: 2, sequence_order: 0 }], customers: [], items: [] }),
    ) as unknown as Fetcher;
    const { engine, cache } = await buildEngine(fetcher);

    await engine.pull();

    const cached = await cache.getPullResponse();
    expect(cached?.visit_plans).toHaveLength(1);
  });

  it("pushQueue اقدام‌هایِ موفق را از صف حذف می‌کند", async () => {
    const fetcher: Fetcher = jest.fn(async () => jsonResponse(204, undefined)) as unknown as Fetcher;
    const { engine, queue } = await buildEngine(fetcher);
    await queue.enqueue({ type: "COMPLETE_VISIT", payload: { customerVisitId: 1 } });
    await queue.enqueue({ type: "SKIP_VISIT", payload: { customerVisitId: 2, skipReason: "تعطیل" } });

    const result = await engine.pushQueue();

    expect(result.succeeded).toHaveLength(2);
    expect(await queue.size()).toBe(0);
  });

  it("با خطایِ شبکه، بقیه‌یِ صف برایِ تلاشِ بعدی نگه‌داشته می‌شود", async () => {
    let call = 0;
    const fetcher: Fetcher = jest.fn(async () => {
      call += 1;
      if (call === 1) return jsonResponse(204, undefined);
      throw new TypeError("Network request failed");
    }) as unknown as Fetcher;
    const { engine, queue } = await buildEngine(fetcher);
    await queue.enqueue({ type: "COMPLETE_VISIT", payload: { customerVisitId: 1 } });
    await queue.enqueue({ type: "COMPLETE_VISIT", payload: { customerVisitId: 2 } });
    await queue.enqueue({ type: "COMPLETE_VISIT", payload: { customerVisitId: 3 } });

    const result = await engine.pushQueue();

    expect(result.succeeded).toHaveLength(1);
    expect(await queue.size()).toBe(2);
  });

  it("با خطایِ ۴xx (مثلاً ویزیتِ قبلاً بسته‌شده)، اقدام از صف حذف و در failedButKept ثبت می‌شود", async () => {
    const fetcher: Fetcher = jest.fn(async () => jsonResponse(400, { detail: "این ویزیت قبلاً بسته شده است." })) as unknown as Fetcher;
    const { engine, queue } = await buildEngine(fetcher);
    await queue.enqueue({ type: "COMPLETE_VISIT", payload: { customerVisitId: 1 } });

    const result = await engine.pushQueue();

    expect(result.succeeded).toHaveLength(0);
    expect(result.failedButKept).toHaveLength(1);
    expect(result.failedButKept[0].reason).toContain("بسته شده");
    expect(await queue.size()).toBe(0);
  });
});
