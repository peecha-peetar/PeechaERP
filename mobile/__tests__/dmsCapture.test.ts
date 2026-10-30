import { ApiClient, ApiError, Fetcher } from "../src/api/client";
import { addPhoto, canAddPhoto, isOpenStatus, newDraft, removePhoto, replacePhoto, toPayload } from "../src/dms/captureDraft";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { TokenStore } from "../src/storage/tokenStore";

function jsonResponse(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, statusText: String(status), json: async () => body } as unknown as Response;
}

interface SentRequest {
  url: string;
  headers: Record<string, string>;
  body: string;
}

/** XMLHttpRequestِ ساختگی: پاسخ‌ها به ترتیب برمی‌گردند و پیشرفت ارسال هم گزارش می‌شود. */
function installFakeXhr(responses: Array<{ status: number; body: unknown } | "network-error">): SentRequest[] {
  const sent: SentRequest[] = [];
  class FakeXhr {
    status = 0;
    responseText = "";
    timeout = 0;
    upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    ontimeout: (() => void) | null = null;
    private request: SentRequest = { url: "", headers: {}, body: "" };
    open(_method: string, url: string) {
      this.request.url = url;
    }
    setRequestHeader(name: string, value: string) {
      this.request.headers[name] = value;
    }
    send(body: string) {
      this.request.body = body;
      sent.push(this.request);
      const next = responses.shift();
      setTimeout(() => {
        if (!next || next === "network-error") {
          this.onerror?.();
          return;
        }
        this.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
        this.upload.onprogress?.({ lengthComputable: true, loaded: 100, total: 100 });
        this.status = next.status;
        this.responseText = JSON.stringify(next.body);
        this.onload?.();
      }, 0);
    }
  }
  (globalThis as unknown as { XMLHttpRequest: unknown }).XMLHttpRequest = FakeXhr;
  return sent;
}

const row = {
  request_id: 7,
  status: "COMPLETED",
  status_label: "تکمیل شد",
  target_kind: "سند حسابداری",
  target_label: "سند ۱۲",
  expires_at: null,
  max_photos: 3,
  result_document_id: 41,
};

describe("پیش‌نویس عکس‌برداری اسناد", () => {
  it("سقف تعداد عکس را رعایت می‌کند و عکس خالی را نمی‌پذیرد", () => {
    let draft = newDraft(7, 2);
    draft = addPhoto(draft, { uri: "a", base64: "QQ==" });
    draft = addPhoto(draft, { uri: "b", base64: "" });
    expect(draft.photos).toHaveLength(1);
    draft = addPhoto(draft, { uri: "c", base64: "Qw==" });
    expect(canAddPhoto(draft)).toBe(false);
    expect(addPhoto(draft, { uri: "d", base64: "RA==" }).photos).toHaveLength(2);
  });

  it("کلید تکرارنشدن با هر تغییر عکس‌ها عوض می‌شود ولی بدون تغییر ثابت می‌ماند", () => {
    const draft = addPhoto(newDraft(7, 3), { uri: "a", base64: "QQ==" });
    const same = addPhoto(draft, { uri: "b", base64: "" });
    expect(same.uploadKey).toBe(draft.uploadKey);
    const retaken = replacePhoto(draft, 0, { uri: "a2", base64: "Qg==" });
    expect(retaken.uploadKey).not.toBe(draft.uploadKey);
    expect(retaken.photos[0].uri).toBe("a2");
    const removed = removePhoto(retaken, 0);
    expect(removed.photos).toHaveLength(0);
    expect(removed.uploadKey).not.toBe(retaken.uploadKey);
  });

  it("بستهٔ ارسال نام‌های ساده و base64 خام دارد", () => {
    let draft = newDraft(7, 3);
    draft = addPhoto(draft, { uri: "file:///x/IMG 1.jpg", base64: "QQ==" });
    draft = addPhoto(draft, { uri: "file:///x/../../etc", base64: "Qg==" });
    expect(toPayload(draft)).toEqual([
      { name: "photo-1.jpg", data_base64: "QQ==" },
      { name: "photo-2.jpg", data_base64: "Qg==" },
    ]);
  });

  it("فقط درخواست باز قابل ارسال است", () => {
    expect(["PENDING", "OPENED", "CAPTURING", "UPLOADING"].every(isOpenStatus)).toBe(true);
    expect(["COMPLETED", "CANCELLED", "EXPIRED", "FAILED"].some(isOpenStatus)).toBe(false);
  });
});

describe("ApiClient: درخواست‌های عکس‌برداری", () => {
  it("فهرست، بازکردن و لغو را به مسیرهای درست می‌فرستد", async () => {
    const store = new TokenStore(new InMemoryKeyValueStore());
    await store.setTokens("acc", "ref");
    const calls: Array<{ url: string; method: string; auth: string }> = [];
    const fetcher: Fetcher = jest.fn(async (url: any, init: any) => {
      calls.push({ url: String(url), method: init?.method ?? "GET", auth: init?.headers?.Authorization ?? "" });
      return jsonResponse(200, String(url).endsWith("/requests") ? [row] : row);
    }) as unknown as Fetcher;
    const client = new ApiClient("http://api.local", store, fetcher);

    expect(await client.listCaptureRequests()).toEqual([row]);
    await client.openCaptureRequest(7);
    await client.markCaptureCapturing(7);
    await client.cancelCaptureRequest(7);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET http://api.local/dms/capture/requests",
      "POST http://api.local/dms/capture/requests/7/open",
      "POST http://api.local/dms/capture/requests/7/capturing",
      "POST http://api.local/dms/capture/requests/7/cancel",
    ]);
    expect(calls.every((c) => c.auth === "Bearer acc")).toBe(true);
  });

  it("ارسال عکس با کلید تکرارنشدن و درصد پیشرفت", async () => {
    const store = new TokenStore(new InMemoryKeyValueStore());
    await store.setTokens("acc", "ref");
    const sent = installFakeXhr([{ status: 200, body: row }]);
    const client = new ApiClient("http://api.local", store, jest.fn() as unknown as Fetcher);
    const progress: number[] = [];

    const result = await client.uploadCapturePhotos(7, [{ name: "photo-1.jpg", data_base64: "QQ==" }], "key-1", (p) => progress.push(p));

    expect(result.result_document_id).toBe(41);
    expect(progress).toEqual([50, 100]);
    expect(sent[0].url).toBe("http://api.local/dms/capture/requests/7/upload");
    expect(sent[0].headers["Idempotency-Key"]).toBe("key-1");
    expect(sent[0].headers["Authorization"]).toBe("Bearer acc");
    expect(JSON.parse(sent[0].body)).toEqual({ photos: [{ name: "photo-1.jpg", data_base64: "QQ==" }] });
  });

  it("با توکن منقضی یک‌بار رفرش می‌کند و با همان کلید دوباره می‌فرستد", async () => {
    const store = new TokenStore(new InMemoryKeyValueStore());
    await store.setTokens("old", "ref");
    const sent = installFakeXhr([{ status: 401, body: { detail: "منقضی" } }, { status: 200, body: row }]);
    const fetcher: Fetcher = jest.fn(async () => jsonResponse(200, { access_token: "fresh" })) as unknown as Fetcher;
    const client = new ApiClient("http://api.local", store, fetcher);

    await client.uploadCapturePhotos(7, [{ name: "photo-1.jpg", data_base64: "QQ==" }], "key-2");

    expect(sent).toHaveLength(2);
    expect(sent[1].headers["Authorization"]).toBe("Bearer fresh");
    expect(sent[1].headers["Idempotency-Key"]).toBe("key-2");
  });

  it("پیام فارسی سرور را برمی‌گرداند و قطع ارتباط را خطای قابل تکرار می‌داند", async () => {
    const store = new TokenStore(new InMemoryKeyValueStore());
    await store.setTokens("acc", "ref");
    installFakeXhr([{ status: 410, body: { detail: "مهلت این درخواست تمام شده است." } }, "network-error"]);
    const client = new ApiClient("http://api.local", store, jest.fn() as unknown as Fetcher);

    const expired = await client.uploadCapturePhotos(7, [{ name: "p.jpg", data_base64: "QQ==" }], "k").catch((e) => e);
    expect(expired).toBeInstanceOf(ApiError);
    expect(expired.status).toBe(410);
    expect(expired.message).toBe("مهلت این درخواست تمام شده است.");

    const offline = await client.uploadCapturePhotos(7, [{ name: "p.jpg", data_base64: "QQ==" }], "k").catch((e) => e);
    expect(offline).not.toBeInstanceOf(ApiError);
    expect(offline.message).toContain("قطع");
  });
});
