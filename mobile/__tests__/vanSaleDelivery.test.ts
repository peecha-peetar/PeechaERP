import { ApiClient, Fetcher } from "../src/api/client";
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

const ORDER = {
  document_type_code: "SALES_INVOICE" as const,
  counterparty_detail_account_id: 5,
  warehouse_id: 1,
  channel_code: "VAN_SALES",
  currency_id: 1,
  lines: [{ item_id: 10, uom_id: 1, quantity: "3", unit_price: "1000" }],
  post_immediately: true,
};

describe("CREATE_VAN_SALE_DELIVERY (اقدامِ ترکیبیِ سفارش+تاییدِ تحویلِ پخشِ گرم)", () => {
  it("سفارش را می‌سازد و بلافاصله با document_line_idِ برگشتی رسیدِ تحویل می‌فرستد", async () => {
    const calls: { url: string; body: unknown; headers: Record<string, string> }[] = [];
    const fetcher: Fetcher = jest.fn(async (url: any, init: any) => {
      calls.push({ url: String(url), body: init?.body ? JSON.parse(init.body) : undefined, headers: init?.headers });
      if (String(url).endsWith("/orders")) return jsonResponse(200, { document_id: 42, line_ids: [777] });
      if (String(url).endsWith("/delivery-confirmations")) return jsonResponse(200, { delivery_confirmation_id: 9 });
      throw new Error("unexpected url " + url);
    }) as unknown as Fetcher;
    const { engine, queue } = await buildEngine(fetcher);

    await queue.enqueue({
      type: "CREATE_VAN_SALE_DELIVERY",
      payload: { order: ORDER, delivery: { received_by_name: "علی", notes: null } },
    });

    const result = await engine.pushQueue();

    expect(result.succeeded).toHaveLength(1);
    expect(await queue.size()).toBe(0);
    const deliveryCall = calls.find((c) => c.url.endsWith("/delivery-confirmations"))!;
    expect((deliveryCall.body as any).document_id).toBe(42);
    expect((deliveryCall.body as any).lines).toEqual([{ document_line_id: 777, delivered_quantity: "3" }]);
    // کلیدِ idempotency برایِ نیمه‌یِ دوم باید مشتق از همان کلیدِ اقدام باشد، نه تصادفی
    const orderCall = calls.find((c) => c.url.endsWith("/orders"))!;
    expect(deliveryCall.headers["Idempotency-Key"]).toBe(`${orderCall.headers["Idempotency-Key"]}:delivery`);
  });

  it("اگر بعدِ موفقیتِ سفارش، تاییدِ تحویل با قطعیِ شبکه مواجه شود، سفارش دوباره ساخته نمی‌شود", async () => {
    let orderCallCount = 0;
    let deliveryCallCount = 0;
    const fetcher: Fetcher = jest.fn(async (url: any) => {
      if (String(url).endsWith("/orders")) {
        orderCallCount += 1;
        return jsonResponse(200, { document_id: 42, line_ids: [777] });
      }
      if (String(url).endsWith("/delivery-confirmations")) {
        deliveryCallCount += 1;
        if (deliveryCallCount === 1) throw new TypeError("Network request failed");
        return jsonResponse(200, { delivery_confirmation_id: 9 });
      }
      throw new Error("unexpected url " + url);
    }) as unknown as Fetcher;
    const { engine, queue } = await buildEngine(fetcher);
    await queue.enqueue({
      type: "CREATE_VAN_SALE_DELIVERY",
      payload: { order: ORDER, delivery: { received_by_name: "علی", notes: null } },
    });

    const first = await engine.pushQueue();
    expect(first.succeeded).toHaveLength(0);
    expect(await queue.size()).toBe(1);
    expect(orderCallCount).toBe(1);

    const second = await engine.pushQueue();
    expect(second.succeeded).toHaveLength(1);
    expect(await queue.size()).toBe(0);
    expect(orderCallCount).toBe(1); // سفارش فقط یک‌بار ساخته شد
    expect(deliveryCallCount).toBe(2);
  });

  it("اگر تاییدِ تحویل با خطایِ ۴xx شکست بخورد، از صف حذف می‌شود ولی document_id در نتیجه گزارش می‌شود", async () => {
    const fetcher: Fetcher = jest.fn(async (url: any) => {
      if (String(url).endsWith("/orders")) return jsonResponse(200, { document_id: 42, line_ids: [777] });
      return jsonResponse(400, { detail: "خطایِ اعتبارسنجیِ رسیدِ تحویل" });
    }) as unknown as Fetcher;
    const { engine, queue } = await buildEngine(fetcher);
    await queue.enqueue({
      type: "CREATE_VAN_SALE_DELIVERY",
      payload: { order: ORDER, delivery: { received_by_name: "علی", notes: null } },
    });

    const result = await engine.pushQueue();

    expect(result.failedButKept).toHaveLength(1);
    expect(result.failedButKept[0].documentId).toBe(42);
    expect(await queue.size()).toBe(0);
  });
});
