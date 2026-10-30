import { ApiClient } from "./api/client";
import { API_BASE_URL } from "./config";
import { AsyncStorageKeyValueStore } from "./storage/asyncStorageAdapter";
import { CatalogCache } from "./storage/catalogCache";
import { KeyValueStore } from "./storage/keyValueStore";
import { LocalCache } from "./storage/localCache";
import { TokenStore } from "./storage/tokenStore";
import { OfflineQueue } from "./sync/offlineQueue";
import { SyncEngine } from "./sync/syncEngine";
import { SyncErrorLog } from "./sync/syncErrorLog";
import { InvoiceResultStore } from "./sync/invoiceResults";
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
  const invoiceResults = new InvoiceResultStore(kvStore);
  const syncEngine = new SyncEngine(apiClient, offlineQueue, localCache, visitCorrelation, invoiceResults);
  const syncErrorLog = new SyncErrorLog(kvStore);
  const catalogCache = new CatalogCache(kvStore);
  return { kvStore, tokenStore, apiClient, offlineQueue, localCache, syncEngine, syncErrorLog, invoiceResults, catalogCache };
}

export type Services = ReturnType<typeof createServices>;
