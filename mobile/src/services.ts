import { ApiClient } from "./api/client";
import { API_BASE_URL } from "./config";
import { AsyncStorageKeyValueStore } from "./storage/asyncStorageAdapter";
import { KeyValueStore } from "./storage/keyValueStore";
import { LocalCache } from "./storage/localCache";
import { TokenStore } from "./storage/tokenStore";
import { OfflineQueue } from "./sync/offlineQueue";
import { SyncEngine } from "./sync/syncEngine";
import { VisitCorrelationStore } from "./sync/visitCorrelation";

/** ساختِ همه‌یِ سرویس‌هایِ لایه‌یِ منطق در یک‌جا -- زیرِ Expo Go،
 * AsyncStorageKeyValueStore پیاده‌سازیِ واقعیِ ذخیره‌سازیِ ماندگار است
 * (قبلاً به‌خاطرِ نبودِ Android SDK/Xcode در سندباکس با InMemoryKeyValueStore
 * جایگزین شده بود -- تست‌ها همچنان مستقیماً InMemoryKeyValueStore را برایِ
 * ساختِ SyncEngine/OfflineQueue/... به‌کار می‌برند، نه از این تابع). */
export function createServices(kvStore: KeyValueStore = new AsyncStorageKeyValueStore()) {
  const tokenStore = new TokenStore(kvStore);
  const apiClient = new ApiClient(API_BASE_URL, tokenStore);
  const offlineQueue = new OfflineQueue(kvStore);
  const localCache = new LocalCache(kvStore);
  // طبقِ رفعِ باگِ واقعی (customer_visit_idِ COMPLETE/SKIP_VISIT): باید
  // رویِ همان kvStoreِ اشتراکی باشد، نه یک نمونهٔ جدا -- وگرنه نگاشت با
  // هر بارِ ساختِ SyncEngine از دست می‌رود.
  const visitCorrelation = new VisitCorrelationStore(kvStore);
  const syncEngine = new SyncEngine(apiClient, offlineQueue, localCache, visitCorrelation);
  return { kvStore, tokenStore, apiClient, offlineQueue, localCache, syncEngine };
}

export type Services = ReturnType<typeof createServices>;
