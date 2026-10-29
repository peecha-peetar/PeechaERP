import { ApiClient, Fetcher } from "../src/api/client";
import { buildLeaveRequest, minutesLabel, payslipTitle } from "../src/selfService";
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
  const engine = new SyncEngine(api, queue, new LocalCache(kv), new VisitCorrelationStore(kv), new InvoiceResultStore(kv));
  return { api, calls, queue, engine };
}

const form = { leaveType: "ANNUAL", fromText: "۱۴۰۵/۰۸/۱۵", toText: "", hoursText: "", reason: " سفر " };

describe("Self-service (R360)", () => {
  it("فرم مرخصی: تاریخ شمسی به میلادی، یک‌روزه با تاریخ پایان خالی، و خطاهای روشن", () => {
    expect(buildLeaveRequest(form)).toEqual({
      payload: { leave_type: "ANNUAL", from_date: "2026-11-06", to_date: "2026-11-06", hours: null, reason: "سفر" },
    });
    expect(buildLeaveRequest({ ...form, toText: "1405/8/17" })).toMatchObject({ payload: { to_date: "2026-11-08" } });
    expect(buildLeaveRequest({ ...form, fromText: "۱۴۰۵/۱۳/۰۱" })).toEqual({ error: "تاریخ شروع نامعتبر است (مثلاً ۱۴۰۵/۰۸/۱۵)." });
    expect(buildLeaveRequest({ ...form, toText: "۱۴۰۵/۰۸/۱۰" })).toEqual({ error: "تاریخ پایان نباید پیش از تاریخ شروع باشد." });
    expect(buildLeaveRequest({ ...form, leaveType: "HOURLY", hoursText: "۲٫۵" })).toMatchObject({ payload: { hours: "2.5" } });
    expect(buildLeaveRequest({ ...form, leaveType: "HOURLY", hoursText: "" })).toEqual({ error: "تعداد ساعت مرخصی را درست وارد کنید." });
  });

  it("عنوان فیش و برچسب دقیقه‌ها فارسی است", () => {
    expect(payslipTitle({ jalali_year: 1405, jalali_month: 1 })).toBe("فروردین ۱۴۰۵");
    expect(minutesLabel(20)).toBe("۲۰ دقیقه");
    expect(minutesLabel(85)).toBe("۱ ساعت و ۲۵ دقیقه");
    expect(minutesLabel(120)).toBe("۲ ساعت");
    expect(minutesLabel(0)).toBe("");
  });

  it("درخواست مرخصی از صف آفلاین با کلید یکتای همان اقدام ارسال می‌شود", async () => {
    const { calls, queue, engine } = await build(() => jsonResponse(201, { leave_request_id: 7, status_code: "SUBMITTED" }));
    const built = buildLeaveRequest(form);
    if (!("payload" in built)) throw new Error("bad form");
    const action = await queue.enqueue({ type: "SELF_LEAVE_REQUEST", payload: built.payload });
    const result = await engine.pushQueue();
    expect(result.succeeded).toHaveLength(1);
    expect(await queue.size()).toBe(0);
    expect(calls).toEqual([{ url: "/self/leave", method: "POST", body: built.payload, idem: action.idempotencyKey }]);
  });

  it("رد سرور (همپوشانی مرخصی) صف را قفل نمی‌کند", async () => {
    const { queue, engine } = await build(() => jsonResponse(400, { detail: "برای این بازه یک مرخصی دیگر ثبت شده است." }));
    const built = buildLeaveRequest(form);
    if (!("payload" in built)) throw new Error("bad form");
    await queue.enqueue({ type: "SELF_LEAVE_REQUEST", payload: built.payload });
    const result = await engine.pushQueue();
    expect(result.succeeded).toHaveLength(0);
    expect(await queue.size()).toBe(0);
  });

  it("فیش، حضور و لغو مرخصی از همان مسیرهای سرور خوانده می‌شوند", async () => {
    const { api, calls } = await build(() => jsonResponse(200, []));
    await api.getSelfPayslips();
    await api.getSelfPayslip(3);
    await api.getSelfAttendance(14);
    await api.cancelSelfLeave(7);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /self/payslips", "GET /self/payslips/3", "GET /self/attendance?days=14", "POST /self/leave/7/cancel",
    ]);
  });
});
