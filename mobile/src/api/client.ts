import { TokenStore } from "../storage/tokenStore";
import {
  DeliveryConfirmationRequest,
  DeliveryConfirmationResponse,
  LoginResponse,
  OrderCreateRequest,
  OrderCreateResponse,
  PriceResolveRequest,
  PriceResolveResponse,
  PullResponse,
  StartVisitRequest,
  StartVisitResponse,
} from "./types";

export type Fetcher = typeof fetch;

/** خطایِ HTTP با کدِ وضعیت و پیامِ سرور -- برایِ نمایشِ پیامِ فارسیِ
 * برگشتی از FastAPI (فیلدِ detail) مستقیماً در UI. */
export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

/** کلاینتِ HTTPِ لایهٔ API (peecha_api) -- طبقِ طراحیِ R131: توکنِ
 * دسترسی کوتاه‌مدت است، پس روی هر ۴۰۱ یک‌بار خودکار با رفرش‌توکن تمدید
 * و درخواست تکرار می‌شود؛ اگر رفرش هم شکست بخورد، ApiError با status=401
 * پرتاب می‌شود تا لایه‌یِ UI کاربر را به صفحه‌یِ ورود برگرداند. */
export class ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly tokenStore: TokenStore,
    private readonly fetcher: Fetcher = fetch,
  ) {}

  private async request<T>(
    path: string,
    options: { method?: string; body?: unknown; auth?: boolean; idempotencyKey?: string } = {},
  ): Promise<T> {
    const { method = "GET", body, auth = true, idempotencyKey } = options;
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
    if (auth) {
      const token = await this.tokenStore.getAccessToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
    }
    const doFetch = () =>
      this.fetcher(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });

    let response = await doFetch();
    if (response.status === 401 && auth) {
      const refreshed = await this.tryRefresh();
      if (refreshed) {
        headers["Authorization"] = `Bearer ${await this.tokenStore.getAccessToken()}`;
        response = await doFetch();
      }
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new ApiError(response.status, payload.detail ?? response.statusText);
    }
    if (response.status === 204) return undefined as unknown as T;
    return (await response.json()) as T;
  }

  private async tryRefresh(): Promise<boolean> {
    const refreshToken = await this.tokenStore.getRefreshToken();
    if (!refreshToken) return false;
    try {
      const response = await this.fetcher(`${this.baseUrl}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) return false;
      const data = (await response.json()) as { access_token: string };
      await this.tokenStore.setAccessToken(data.access_token);
      return true;
    } catch {
      return false;
    }
  }

  async login(username: string, password: string, deviceName?: string): Promise<LoginResponse> {
    const data = await this.request<LoginResponse>("/auth/login", {
      method: "POST",
      auth: false,
      body: { username, password, device_name: deviceName ?? null },
    });
    await this.tokenStore.setTokens(data.access_token, data.refresh_token);
    return data;
  }

  async logout(): Promise<void> {
    const refreshToken = await this.tokenStore.getRefreshToken();
    if (refreshToken) {
      await this.request<void>("/auth/logout", { method: "POST", body: { refresh_token: refreshToken } }).catch(
        () => undefined,
      );
    }
    await this.tokenStore.clear();
  }

  async pullSync(): Promise<PullResponse> {
    return this.request<PullResponse>("/sync/pull");
  }

  async startVisit(payload: StartVisitRequest, idempotencyKey?: string): Promise<StartVisitResponse> {
    return this.request<StartVisitResponse>("/visits/start", { method: "POST", body: payload, idempotencyKey });
  }

  async completeVisit(customerVisitId: number, notes?: string): Promise<void> {
    await this.request<void>(`/visits/${customerVisitId}/complete`, { method: "POST", body: { notes: notes ?? null } });
  }

  async skipVisit(customerVisitId: number, skipReason: string): Promise<void> {
    await this.request<void>(`/visits/${customerVisitId}/skip`, {
      method: "POST",
      body: { skip_reason: skipReason },
    });
  }

  async createOrder(payload: OrderCreateRequest, idempotencyKey?: string): Promise<OrderCreateResponse> {
    return this.request<OrderCreateResponse>("/orders", { method: "POST", body: payload, idempotencyKey });
  }

  async createDeliveryConfirmation(
    payload: DeliveryConfirmationRequest,
    idempotencyKey?: string,
  ): Promise<DeliveryConfirmationResponse> {
    return this.request<DeliveryConfirmationResponse>("/delivery-confirmations", {
      method: "POST",
      body: payload,
      idempotencyKey,
    });
  }

  /** طبقِ R133: قیمتِ معتبر را از همان زنجیره‌یِ resolve_price می‌گیرد --
   * فقط وقتی آنلاین هستیم صدا زده می‌شود؛ در آفلاین صفحه‌یِ سفارش باید
   * به ورودیِ دستیِ قیمت برگردد (این متد اصلاً صدا زده نمی‌شود). */
  async resolvePrice(params: PriceResolveRequest): Promise<PriceResolveResponse> {
    const query = new URLSearchParams({
      counterparty_detail_account_id: String(params.counterpartyDetailAccountId),
      item_id: String(params.itemId),
      uom_id: String(params.uomId),
      quantity: params.quantity,
      document_type_code: params.documentTypeCode,
    });
    return this.request<PriceResolveResponse>(`/pricing/resolve?${query.toString()}`);
  }
}
