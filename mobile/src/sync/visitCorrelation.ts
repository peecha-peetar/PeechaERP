import { KeyValueStore } from "../storage/keyValueStore";

const KEY_PREFIX = "peecha.visit_correlation.";

/** رفعِ باگِ واقعی: COMPLETE_VISIT/SKIP_VISIT به customer_visit_id نیاز
 * دارند که فقط بعدِ Syncِ موفقِ START_VISIT از سرور مشخص می‌شود -- ولی
 * برخلافِ سفارش+تاییدِ تحویل (که در یک submit اتفاق می‌افتند و می‌توانند
 * یک اقدامِ صفِ ترکیبی باشند)، شروع/پایانِ ویزیت دو کنشِ کاربرِ کاملاً
 * جدا در زمان‌اند (ویزیتور اول می‌آید، بعد از چند دقیقه تمام می‌کند) --
 * پس نمی‌توانند یک اقدامِ واحد باشند. راه‌حل: شناسه‌یِ همبستگی (همان
 * idempotencyKeyِ اقدامِ START_VISIT) بینِ آن‌ها ذخیره‌سازیِ ماندگار
 * می‌شود -- حتی اگر START_VISIT خیلی قبل‌تر Sync و از صف حذف شده باشد،
 * این نگاشت (نه خودِ صف) جواب را نگه می‌دارد. */
export class VisitCorrelationStore {
  constructor(private readonly kv: KeyValueStore) {}

  async resolve(startActionKey: string, customerVisitId: number): Promise<void> {
    await this.kv.setItem(KEY_PREFIX + startActionKey, String(customerVisitId));
  }

  async get(startActionKey: string): Promise<number | null> {
    const raw = await this.kv.getItem(KEY_PREFIX + startActionKey);
    return raw === null ? null : Number(raw);
  }

  async clear(startActionKey: string): Promise<void> {
    await this.kv.removeItem(KEY_PREFIX + startActionKey);
  }
}
