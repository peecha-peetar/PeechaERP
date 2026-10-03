import AsyncStorage from "@react-native-async-storage/async-storage";
import { KeyValueStore } from "./keyValueStore";

/** پیاده‌سازیِ واقعیِ KeyValueStore رویِ @react-native-async-storage/async-storage
 * -- طبقِ یادداشتِ keyValueStore.ts، این همان پیاده‌سازیِ نهایی است که قبلاً
 * چون در سندباکسِ بدونِ Android SDK/Xcode قابلِ‌کامپایل نبود جایگزین نشده بود؛
 * زیرِ Expo Go این پکیج بدونِ هیچ بیلدِ نیتیوِ سفارشی کار می‌کند. */
export class AsyncStorageKeyValueStore implements KeyValueStore {
  async getItem(key: string): Promise<string | null> {
    return AsyncStorage.getItem(key);
  }

  async setItem(key: string, value: string): Promise<void> {
    await AsyncStorage.setItem(key, value);
  }

  async removeItem(key: string): Promise<void> {
    await AsyncStorage.removeItem(key);
  }
}
