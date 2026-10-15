import { ApiClient, Fetcher } from "../src/api/client";
import { WorkInboxItem } from "../src/api/workflowTypes";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { LocalCache } from "../src/storage/localCache";
import { TokenStore } from "../src/storage/tokenStore";
import { InvoiceResultStore } from "../src/sync/invoiceResults";
import { OfflineQueue } from "../src/sync/offlineQueue";
import { SyncEngine } from "../src/sync/syncEngine";
import { VisitCorrelationStore } from "../src/sync/visitCorrelation";
import { filterInbox, needsComment, needsStepUp, pathText } from "../src/workflow";

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
  return { calls, queue, engine, api };
}

function item(over: Partial<WorkInboxItem>): WorkInboxItem {
  return {
    key: "WF:1", source: "WF", source_label: "گردش کار", kind: "APPROVAL", kind_label: "تایید", ref_id: 1, title: "تایید",
    subtitle: "", due_at: null, is_overdue: false, priority_code: "NORMAL", priority_label: "عادی", created_at: null,
    can_decide: true, status_note: "", definition: null, ...over,
  };
}

describe("گردش کار موبایل (R297)", () => {
  it("تصمیم، یادداشت و سپردن با کلید یکتای هر اقدام از صف آفلاین فرستاده می‌شوند", async () => {
    const { calls, queue, engine } = await build(() => jsonResponse(200, { task_id: 5, status: "APPROVED", closed: true, message: "ok" }));
    const decide = await queue.enqueue({ type: "WF_DECIDE", payload: { taskId: 5, decision: "APPROVE", comment: "", rowVersion: 3 } });
    await queue.enqueue({ type: "WF_COMMENT", payload: { taskId: 5, text: "فاکتور پیوست شد" } });
    await queue.enqueue({ type: "WF_DELEGATE", payload: { taskId: 6, toUserId: 9, comment: "در سفرم" } });

    const result = await engine.pushQueue();

    expect(result.succeeded).toHaveLength(3);
    expect(await queue.size()).toBe(0);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "POST /workflow/tasks/5/decide", "POST /workflow/tasks/5/comment", "POST /workflow/tasks/6/delegate",
    ]);
    expect(calls[0].idem).toBe(decide.idempotencyKey);
    expect(calls[0].body).toEqual({ decision: "APPROVE", comment: "", row_version: 3 });
    expect(calls[2].body).toEqual({ to_user_id: 9, comment: "در سفرم" });
  });

  it("تصمیم ردشده توسط سرور (کار بسته شده) از صف حذف و دلیلش نگه داشته می‌شود", async () => {
    const { queue, engine } = await build(() => jsonResponse(400, { detail: "این کار دیگر باز نیست." }));
    await queue.enqueue({ type: "WF_DECIDE", payload: { taskId: 5, decision: "REJECT", comment: "ناقص" } });

    const result = await engine.pushQueue();

    expect(result.failedButKept[0].reason).toBe("این کار دیگر باز نیست.");
    expect(await queue.size()).toBe(0);
  });

  it("بدون اینترنت تصمیم در صف می‌ماند", async () => {
    const { queue, engine } = await build(() => { throw new Error("network"); });
    await queue.enqueue({ type: "WF_DECIDE", payload: { taskId: 5, decision: "APPROVE", comment: "" } });

    const result = await engine.pushQueue();

    expect(result.succeeded).toHaveLength(0);
    expect(await queue.size()).toBe(1);
  });

  it("تایید حساس با رمز مستقیم و آنلاین فرستاده می‌شود (رمز در صف نمی‌رود)", async () => {
    const { calls, api, queue } = await build(() => jsonResponse(200, { task_id: 7, status: "APPROVED", closed: true, message: "ok" }));
    await api.decideWorkTask(7, { decision: "APPROVE", comment: "", password: "secret" });
    expect(calls[0].body?.password).toBe("secret");
    expect(await queue.size()).toBe(0);
  });

  it("کمک‌ها: فیلتر کارتابل، نیاز به رمز و توضیح، متن مسیر", () => {
    const rows = [item({ key: "a" }), item({ key: "b", kind: "TASK", is_overdue: true })];
    expect(filterInbox(rows, "APPROVAL").map((r) => r.key)).toEqual(["a"]);
    expect(filterInbox(rows, "TASK").map((r) => r.key)).toEqual(["b"]);
    expect(filterInbox(rows, "OVERDUE").map((r) => r.key)).toEqual(["b"]);
    expect(needsStepUp({ requires_step_up: true }, "APPROVE")).toBe(true);
    expect(needsStepUp({ requires_step_up: true }, "REJECT")).toBe(false);
    expect(needsStepUp({ requires_step_up: false }, "APPROVE")).toBe(false);
    expect(needsComment("REJECT") && needsComment("CHANGES") && !needsComment("APPROVE")).toBe(true);
    expect(pathText([{ label: "ثبت", state: "done" }, { label: "تایید مالی", state: "current" }]))
      .toBe("ثبت (انجام‌شده) ← تایید مالی (در جریان)");
  });
});
