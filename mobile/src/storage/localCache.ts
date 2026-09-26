import { KeyValueStore } from "./keyValueStore";
import { NewCustomerFormOptions, PullResponse } from "../api/types";

const PULL_CACHE_KEY = "peecha.pull_cache";
const NEW_CUSTOMER_FORM_OPTIONS_KEY = "peecha.new_customer_form_options_cache";

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

  /** طبقِ بازبینیِ صریحِ کاربر (R218): وقتی گروهِ مشتری چندسطحی
   * پیکربندی شده، انتخابِ والد بدونِ این گزینه‌ها ممکن نیست -- بدونِ این
   * کش، هر بارِ آفلاین‌بودنِ فرمِ «مشتریِ جدید» یعنی فرم اشتباهاً فرض
   * می‌کند تک‌سطحی است. آخرین دریافتِ موفق نگه‌داشته می‌شود تا فرم در
   * آفلاین هم بتواند سطحِ درست را بشناسد. */
  async saveNewCustomerFormOptions(data: NewCustomerFormOptions): Promise<void> {
    await this.kv.setItem(NEW_CUSTOMER_FORM_OPTIONS_KEY, JSON.stringify(data));
  }

  async getNewCustomerFormOptions(): Promise<NewCustomerFormOptions | null> {
    const raw = await this.kv.getItem(NEW_CUSTOMER_FORM_OPTIONS_KEY);
    if (raw === null) return null;
    return JSON.parse(raw) as NewCustomerFormOptions;
  }
}
