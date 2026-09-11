import { ApiClient } from "./api/client";
import { API_BASE_URL } from "./config";
import { InMemoryKeyValueStore, KeyValueStore } from "./storage/keyValueStore";
import { LocalCache } from "./storage/localCache";
import { TokenStore } from "./storage/tokenStore";
import { OfflineQueue } from "./sync/offlineQueue";
import { SyncEngine } from "./sync/syncEngine";

/** ساختِ همه‌یِ سرویس‌هایِ لایه‌یِ منطق در یک‌جا -- در اپِ واقعی،
 * kvStore با AsyncStorageAdapter (پیاده‌سازیِ KeyValueStore رویِ
 * @react-native-async-storage/async-storage) جایگزین می‌شود؛ چون آن
 * پکیج در این سندباکس قابلِ‌کامپایل/تست نیست، فعلاً از InMemoryKeyValueStore
 * استفاده شده -- منطق (offlineQueue/syncEngine/apiClient) کاملاً همان
 * است و فقط لایه‌یِ ذخیره‌سازیِ فیزیکی عوض می‌شود. */
export function createServices(kvStore: KeyValueStore = new InMemoryKeyValueStore()) {
  const tokenStore = new TokenStore(kvStore);
  const apiClient = new ApiClient(API_BASE_URL, tokenStore);
  const offlineQueue = new OfflineQueue(kvStore);
  const localCache = new LocalCache(kvStore);
  const syncEngine = new SyncEngine(apiClient, offlineQueue, localCache);
  return { tokenStore, apiClient, offlineQueue, localCache, syncEngine };
}

export type Services = ReturnType<typeof createServices>;
