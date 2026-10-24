import { ApiClient, Fetcher } from "../src/api/client";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { LocalCache } from "../src/storage/localCache";
import { TokenStore } from "../src/storage/tokenStore";
import { InvoiceResultStore } from "../src/sync/invoiceResults";
import { OfflineQueue } from "../src/sync/offlineQueue";
import { SyncEngine } from "../src/sync/syncEngine";
import { VisitCorrelationStore } from "../src/sync/visitCorrelation";

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
  const correlation = new VisitCorrelationStore(kv);
  const engine = new SyncEngine(api, queue, new LocalCache(kv), correlation, new InvoiceResultStore(kv));
  return { calls, queue, engine, correlation };
}

describe("CRM offline sync (R286)", () => {
  it("سرنخ، تیکت و انجام کار با کلید یکتای هر اقدام ارسال می‌شوند", async () => {
    const { calls, queue, engine } = await build(() => jsonResponse(200, { lead_id: 1, ticket_id: 2, activity_id: 3 }));
    const lead = await queue.enqueue({ type: "CRM_CREATE_LEAD", payload: { full_name: "علی", mobile: "09120000000", allow_duplicate: true } });
    await queue.enqueue({
      type: "CRM_CREATE_TICKET",
      payload: { customer_detail_account_id: 7, subject: "تأخیر", ticket_type: "COMPLAINT", priority_code: "HIGH", channel_code: "MOBILE_APP" },
    });
    await queue.enqueue({ type: "CRM_COMPLETE_ACTIVITY", payload: { activityId: 9, result_text: "انجام شد", follow_up_date: "2026-11-01" } });

    const result = await engine.pushQueue();

    expect(result.succeeded).toHaveLength(3);
    expect(await queue.size()).toBe(0);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "POST /crm/leads", "POST /crm/tickets", "POST /crm/activities/9/complete",
    ]);
    expect(calls[0].idem).toBe(lead.idempotencyKey);
    expect(calls[2].body).toEqual({ result_text: "انجام شد", follow_up_date: "2026-11-01" });
  });

  it("پیگیری پس از ویزیت شناسهٔ ویزیت همگام‌شده را می‌گیرد و کلید داخلی را نمی‌فرستد", async () => {
    const { calls, queue, engine, correlation } = await build(() => jsonResponse(200, { activity_id: 4 }));
    await correlation.resolve("start-key", 55);
    await queue.enqueue({
      type: "CRM_CREATE_ACTIVITY",
      payload: { activity_type_code: "FOLLOW_UP", subject: "پیگیری", customer_detail_account_id: 7, due_date: "2026-11-01", visitStartActionKey: "start-key" },
    });

    await engine.pushQueue();

    expect(calls[0].url).toBe("/crm/activities");
    expect(calls[0].body?.customer_visit_id).toBe(55);
    expect(calls[0].body).not.toHaveProperty("visitStartActionKey");
  });

  it("پیگیری بدون شناسهٔ ویزیت رد نمی‌شود", async () => {
    const { calls, queue, engine } = await build(() => jsonResponse(200, { activity_id: 4 }));
    await queue.enqueue({
      type: "CRM_CREATE_ACTIVITY",
      payload: { activity_type_code: "FOLLOW_UP", subject: "پیگیری", customer_detail_account_id: 7, visitStartActionKey: "unknown" },
    });

    const result = await engine.pushQueue();

    expect(result.succeeded).toHaveLength(1);
    expect(calls[0].body?.customer_visit_id).toBeNull();
  });

  it("خطای ۴xx سرنخ را از صف حذف و گزارش می‌کند؛ خطای شبکه نگه می‌دارد", async () => {
    let n = 0;
    const { queue, engine } = await build(() => {
      n += 1;
      if (n === 1) return jsonResponse(400, { detail: "نام سرنخ الزامی است." });
      throw new TypeError("Network request failed");
    });
    await queue.enqueue({ type: "CRM_CREATE_LEAD", payload: { full_name: "" } });
    await queue.enqueue({ type: "CRM_CREATE_TICKET", payload: { customer_detail_account_id: 1, subject: "x", ticket_type: "COMPLAINT", priority_code: "LOW" } });

    const result = await engine.pushQueue();

    expect(result.failedButKept).toHaveLength(1);
    expect(result.failedButKept[0].reason).toContain("نام سرنخ");
    expect(await queue.size()).toBe(1);
  });
});
