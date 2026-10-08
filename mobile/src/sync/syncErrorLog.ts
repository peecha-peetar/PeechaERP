import { KeyValueStore } from "../storage/keyValueStore";

const LOG_KEY = "peecha.sync_error_log";
const MAX_ENTRIES = 20;

export interface SyncErrorEntry {
  idempotencyKey: string;
  reason: string;
  documentId?: number;
  occurredAt: string;
}

/** طبقِ نیازِ واقعیِ کشف‌شده (گزارشِ کاربر رویِ گوشیِ فیزیکی): وقتی یک
 * آیتمِ صف برایِ همیشه شکست می‌خورد (failedButKept در syncEngine)،
 * پیامِ خطایِ واقعی (err.message) از قبل تولید می‌شد اما هیچ‌جا
 * ذخیره/نمایش داده نمی‌شد -- فقط یک نشانهٔ کلیِ «خطا» در AppBar. کاربر
 * برایِ فهمیدنِ چرایی مجبور شد لاگِ خامِ سرورِ uvicorn را دستی بخواند.
 * این کلاس آخرین چند خطا را دائمی ذخیره می‌کند تا در صفحه‌یِ تنظیمات
 * قابلِ‌دیدن باشد -- بدونِ نیازِ کاربر به دسترسیِ سرور. */
export class SyncErrorLog {
  constructor(private readonly kv: KeyValueStore) {}

  async record(entries: { idempotencyKey: string; reason: string; documentId?: number }[]): Promise<void> {
    if (entries.length === 0) return;
    const existing = await this.list();
    const withTimestamp: SyncErrorEntry[] = entries.map((e) => ({ ...e, occurredAt: new Date().toISOString() }));
    const merged = [...withTimestamp, ...existing].slice(0, MAX_ENTRIES);
    await this.kv.setItem(LOG_KEY, JSON.stringify(merged));
  }

  async list(): Promise<SyncErrorEntry[]> {
    const raw = await this.kv.getItem(LOG_KEY);
    if (raw === null) return [];
    try {
      return JSON.parse(raw) as SyncErrorEntry[];
    } catch {
      return [];
    }
  }

  async clear(): Promise<void> {
    await this.kv.removeItem(LOG_KEY);
  }
}
