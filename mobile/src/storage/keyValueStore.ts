/** انتزاعِ حداقلیِ ذخیره‌سازیِ کلید/مقدار -- در اپِ واقعی با
 * @react-native-async-storage/async-storage پیاده می‌شود؛ این‌جا فقط
 * اینترفیس تعریف شده تا منطقِ سینک/توکن بدونِ وابستگی به یک پکیجِ
 * نیتیو (که در این سندباکس قابلِ‌کامپایل/تست نیست) قابلِ‌آزمایش بماند. */
export interface KeyValueStore {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
}

/** پیاده‌سازیِ حافظه‌ای -- برایِ تست‌هایِ Jest و به‌عنوانِ نمونه/الگو. */
export class InMemoryKeyValueStore implements KeyValueStore {
  private data = new Map<string, string>();

  async getItem(key: string): Promise<string | null> {
    return this.data.has(key) ? this.data.get(key)! : null;
  }

  async setItem(key: string, value: string): Promise<void> {
    this.data.set(key, value);
  }

  async removeItem(key: string): Promise<void> {
    this.data.delete(key);
  }
}
