import { ApiClient, Fetcher } from "../src/api/client";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { LocalCache } from "../src/storage/localCache";
import { TokenStore } from "../src/storage/tokenStore";
import { InvoiceResultStore } from "../src/sync/invoiceResults";
import { OfflineQueue } from "../src/sync/offlineQueue";
import { SyncEngine } from "../src/sync/syncEngine";
import { VisitCorrelationStore } from "../src/sync/visitCorrelation";
import { submitWmsAction } from "../src/sync/wmsSubmit";

function jsonResponse(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, statusText: String(status), json: async () => body } as unknown as Response;
}

type Call = { url: string; method: string; body: Record<string, unknown> | null; idem: string | null };

async function build(respond: (call: Call) => Response) {
  const calls: Call[] = [];
  const fetcher = jest.fn(async (url: string, init: RequestInit) => {
    const headers = (init.headers ?? {}) as Record<string, string>;
    const call = {
      url: url.replace("http://api.local", ""), method: init.method ?? "GET",
      body: init.body ? JSON.parse(String(init.body)) : null, idem: headers["Idempotency-Key"] ?? null,
    };
    calls.push(call);
    return respond(call);
  }) as unknown as Fetcher;
  const kv = new InMemoryKeyValueStore();
  const store = new TokenStore(kv);
  await store.setTokens("acc", "ref");
  const api = new ApiClient("http://api.local", store, fetcher);
  const queue = new OfflineQueue(kv);
  const engine = new SyncEngine(api, queue, new LocalCache(kv), new VisitCorrelationStore(kv), new InvoiceResultStore(kv));
  return { calls, queue, engine };
}

describe("Maintenance offline sync (R312)", () => {
  it("درخواست تعمیر، ردیف چک‌لیست و گام دستور کار با کلید یکتای هر اقدام ارسال می‌شوند", async () => {
    const { calls, queue, engine } = await build(() => jsonResponse(200, { request_id: 1, request_no: 1, ok: true, is_ok: true }));
    const req = await queue.enqueue({
      type: "MNT_CREATE_REQUEST",
      payload: { asset_id: 5, title: "نشت روغن", machine_stopped: true, severity_code: "HIGH", scanned: true },
    });
    await queue.enqueue({ type: "MNT_TASK", payload: { taskId: 9, done: true, valueNumeric: "45" } });
    await queue.enqueue({ type: "MNT_ACTION", payload: { workOrderId: 3, action: "complete", body: { note: "انجام شد" } } });

    const result = await engine.pushQueue();

    expect(result.succeeded).toHaveLength(3);
    expect(await queue.size()).toBe(0);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "POST /maintenance/requests", "POST /maintenance/tasks/9", "POST /maintenance/work-orders/3/complete",
    ]);
    expect(calls[0].idem).toBe(req.idempotencyKey);
    expect(calls[1].body).toEqual({ done: true, value_numeric: "45", value_text: null });
    expect(calls[2].body).toEqual({ note: "انجام شد" });
  });

  it("رد سرور (مثلاً ثبت انجام کار دوباره) به تکنسین گفته می‌شود و صف را قفل نمی‌کند", async () => {
    const { queue, engine } = await build(() => jsonResponse(400, { detail: "دستور کار در وضعیت «انجام‌شده، منتظر آزمون» است." }));
    const outcome = await submitWmsAction(queue, engine, {
      type: "MNT_ACTION", payload: { workOrderId: 3, action: "complete", body: { note: "x" } },
    });
    expect(outcome.status).toBe("REJECTED");
    expect(outcome.status === "REJECTED" && outcome.reason).toContain("منتظر آزمون");
    expect(await queue.size()).toBe(0);
  });
});
