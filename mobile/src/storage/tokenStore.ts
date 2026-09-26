import { KeyValueStore } from "./keyValueStore";

const ACCESS_TOKEN_KEY = "peecha.access_token";
const REFRESH_TOKEN_KEY = "peecha.refresh_token";

/** نگه‌داریِ توکنِ دسترسی/رفرشِ همین دستگاه. طبقِ طراحیِ R131، توکنِ
 * دسترسی کوتاه‌مدت است (۲۰ دقیقه) و باید هنگامِ ۴۰۱ با رفرش تمدید شود --
 * این منطق در ApiClient پیاده می‌شود، نه این‌جا. */
export class TokenStore {
  constructor(private readonly kv: KeyValueStore) {}

  async getAccessToken(): Promise<string | null> {
    return this.kv.getItem(ACCESS_TOKEN_KEY);
  }

  async getRefreshToken(): Promise<string | null> {
    return this.kv.getItem(REFRESH_TOKEN_KEY);
  }

  async setTokens(accessToken: string, refreshToken: string): Promise<void> {
    await this.kv.setItem(ACCESS_TOKEN_KEY, accessToken);
    await this.kv.setItem(REFRESH_TOKEN_KEY, refreshToken);
  }

  async setAccessToken(accessToken: string): Promise<void> {
    await this.kv.setItem(ACCESS_TOKEN_KEY, accessToken);
  }

  async clear(): Promise<void> {
    await this.kv.removeItem(ACCESS_TOKEN_KEY);
    await this.kv.removeItem(REFRESH_TOKEN_KEY);
  }
}
