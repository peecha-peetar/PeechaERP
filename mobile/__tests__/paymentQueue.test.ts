import { ApiClient, Fetcher } from "../src/api/client";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { LocalCache } from "../src/storage/localCache";
import { TokenStore } from "../src/storage/tokenStore";
import { OfflineQueue } from "../src/sync/offlineQueue";
import { SyncEngine } from "../src/sync/syncEngine";

function jsonResponse(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, statusText: String(status), json: async () => body } as unknown as Response;
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

/** طبقِ Phase 5/6: ثبتِ وصول هم مثلِ سفارش باید آفلاین صف شود و بعدِ
 * اتصال Sync شود -- بدونِ Duplicate در تلاشِ دوباره (Idempotency-Key). */
describe("CREATE_PAYMENT در صفِ آفلاین", () => {
  it("وصولِ صف‌شده به /payments با Idempotency-Key ارسال می‌شود", async () => {
    const calls: { url: string; headers: Record<string, string> }[] = [];
    const fetcher: Fetcher = jest.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url: String(url), headers: (init?.headers as Record<string, string>) ?? {} });
      return jsonResponse(200, { journal_entry_id: 55, temporary_no: 1 });
    }) as unknown as Fetcher;
    const { engine, queue } = await buildEngine(fetcher);

    await queue.enqueue({
      type: "CREATE_PAYMENT",
      payload: { customer_detail_account_id: 7, method_lines: [{ method: "CASH", amount: "150000" }] },
    });

    const result = await engine.pushQueue();

    expect(result.succeeded).toHaveLength(1);
    const call = calls.find((c) => c.url.endsWith("/payments"));
    expect(call).toBeDefined();
    expect(call?.headers["Idempotency-Key"]).toBeTruthy();
    expect(await queue.size()).toBe(0);
  });

  it("وصولِ ناموفق (۴xx) به‌جایِ توقفِ کلِ صف در failedButKept ثبت می‌شود", async () => {
    const fetcher: Fetcher = jest.fn(async () =>
      jsonResponse(400, { detail: "برایِ این طرفِ‌حساب، نگاشتِ حساب در تنظیماتِ خزانه‌داری تعریف نشده است." }),
    ) as unknown as Fetcher;
    const { engine, queue } = await buildEngine(fetcher);

    await queue.enqueue({
      type: "CREATE_PAYMENT",
      payload: { customer_detail_account_id: 7, method_lines: [{ method: "CASH", amount: "1000" }] },
    });

    const result = await engine.pushQueue();

    expect(result.failedButKept).toHaveLength(1);
    expect(await queue.size()).toBe(0);
  });
});
