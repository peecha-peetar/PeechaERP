import { KeyValueStore } from "./keyValueStore";
import { PullResponse } from "../api/types";

const PULL_CACHE_KEY = "peecha.pull_cache";

/** کشِ محلیِ خروجیِ /sync/pull -- برایِ کارکردِ درست در آفلاین (بدونِ
 * اتصال، همان آخرین pullِ موفق نمایش داده می‌شود). طبقِ تصمیمِ طراحی
 * (سرور-برنده برایِ دیتایِ مشترک)، این کش همیشه با pull بعدی به‌طورِ
 * کامل جایگزین می‌شود، نه merge می‌شود. */
export class LocalCache {
  constructor(private readonly kv: KeyValueStore) {}

  async savePullResponse(data: PullResponse): Promise<void> {
    await this.kv.setItem(PULL_CACHE_KEY, JSON.stringify(data));
  }

  async getPullResponse(): Promise<PullResponse | null> {
    const raw = await this.kv.getItem(PULL_CACHE_KEY);
    if (raw === null) return null;
    return JSON.parse(raw) as PullResponse;
  }
}
