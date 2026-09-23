import * as Location from "expo-location";

export interface Coordinates {
  latitude: number;
  longitude: number;
}

/** انتزاعِ گرفتنِ مختصاتِ GPS -- طبقِ تصمیمِ اجرا زیرِ Expo Go (R187)،
 * پیاده‌سازیِ واقعی با expo-location است (بدونِ نیازِ بیلدِ نیتیوِ
 * سفارشی). NullLocationProvider هم‌چنان برایِ تست‌ها و حالتِ ردِ دسترسی
 * نگه داشته شده است. */
export interface LocationProvider {
  getCurrentPosition(): Promise<Coordinates | null>;
}

export class NullLocationProvider implements LocationProvider {
  async getCurrentPosition(): Promise<Coordinates | null> {
    return null;
  }
}

/** طبقِ رفتارِ موردِانتظار: اگر کاربر دسترسیِ GPS را رد کند یا خطایی رخ
 * دهد، null برمی‌گرداند (نه throw) -- چونِ صفحه‌هایِ صدازننده (Order/
 * Visit/DeliveryConfirm) این را «بدونِ مختصات ادامه بده»، نه خطایِ
 * بلاک‌کننده، تفسیر می‌کنند. */
export class ExpoLocationProvider implements LocationProvider {
  async getCurrentPosition(): Promise<Coordinates | null> {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== "granted") return null;
      const position = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      return { latitude: position.coords.latitude, longitude: position.coords.longitude };
    } catch {
      return null;
    }
  }
}
