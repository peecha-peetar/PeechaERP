import { ApiClient, ApiError, Fetcher } from "../src/api/client";
import { InMemoryKeyValueStore } from "../src/storage/keyValueStore";
import { TokenStore } from "../src/storage/tokenStore";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  } as unknown as Response;
}

describe("ApiClient", () => {
  it("login توکن‌ها را ذخیره می‌کند", async () => {
    const store = new TokenStore(new InMemoryKeyValueStore());
    const fetcher: Fetcher = jest.fn(async () =>
      jsonResponse(200, {
        access_token: "acc-1",
        refresh_token: "ref-1",
        user_id: 2,
        full_name: "ویزیتور",
        company_id: 1,
        company_name: "شرکت",
      }),
    ) as unknown as Fetcher;
    const client = new ApiClient("http://api.local", store, fetcher);

    const result = await client.login("visitor1", "secret");

    expect(result.access_token).toBe("acc-1");
    expect(await store.getAccessToken()).toBe("acc-1");
    expect(await store.getRefreshToken()).toBe("ref-1");
  });

  it("۴۰۱ اتفاق‌افتاده روی توکنِ منقضی، یک‌بار رفرش کرده و درخواست را تکرار می‌کند", async () => {
    const store = new TokenStore(new InMemoryKeyValueStore());
    await store.setTokens("expired-token", "ref-1");

    let call = 0;
    const fetcher: Fetcher = jest.fn(async (url: any) => {
      call += 1;
      if (String(url).endsWith("/sync/pull") && call === 1) {
        return jsonResponse(401, { detail: "توکن منقضی شده" });
      }
      if (String(url).endsWith("/auth/refresh")) {
        return jsonResponse(200, { access_token: "fresh-token" });
      }
      return jsonResponse(200, { visit_plans: [], customers: [], items: [] });
    }) as unknown as Fetcher;
    const client = new ApiClient("http://api.local", store, fetcher);

    const data = await client.pullSync();

    expect(data).toEqual({ visit_plans: [], customers: [], items: [] });
    expect(await store.getAccessToken()).toBe("fresh-token");
  });

  it("خطایِ سرور را با پیامِ فارسیِ detail پرتاب می‌کند", async () => {
    const store = new TokenStore(new InMemoryKeyValueStore());
    await store.setTokens("acc", "ref");
    const fetcher: Fetcher = jest.fn(async () =>
      jsonResponse(400, { detail: "حداقل یک ردیف لازم است." }),
    ) as unknown as Fetcher;
    const client = new ApiClient("http://api.local", store, fetcher);

    await expect(
      client.createOrder({
        document_type_code: "SALES_ORDER",
        counterparty_detail_account_id: 1,
        currency_id: 1,
        warehouse_id: 1,
        channel_code: "PRE_SALES",
        post_immediately: false,
        lines: [],
      }),
    ).rejects.toThrow(ApiError);
  });
});
