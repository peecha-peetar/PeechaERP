export interface Coordinates {
  latitude: number;
  longitude: number;
}

/** انتزاعِ گرفتنِ مختصاتِ GPS -- در اپِ واقعی با یک کتابخانه‌یِ نیتیو
 * (مثلِ react-native-geolocation-service) پیاده می‌شود که در این
 * سندباکس (بدونِ Android SDK/Xcode) قابلِ‌نصب/تستِ واقعی نیست؛ این‌جا
 * فقط اینترفیس + یک پیاده‌سازیِ null (برایِ حالتی که کاربر دسترسیِ GPS
 * را رد کرده) تعریف شده تا صفحه‌ها بدونِ وابستگیِ نیتیو کامپایل/تست شوند. */
export interface LocationProvider {
  getCurrentPosition(): Promise<Coordinates | null>;
}

export class NullLocationProvider implements LocationProvider {
  async getCurrentPosition(): Promise<Coordinates | null> {
    return null;
  }
}
