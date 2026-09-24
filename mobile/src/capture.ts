import * as ImagePicker from "expo-image-picker";

/** انتزاعِ گرفتنِ امضا/عکسِ رسیدِ تحویل. خروجی طبقِ قراردادِ
 * peecha_api.routers.delivery همیشه رشته‌یِ base64ِ خامِ فایل (بدونِ
 * پیشوندِ data:...;base64,) است. */
export interface CaptureProvider {
  captureSignature(): Promise<string | null>;
  capturePhoto(): Promise<string | null>;
}

export class NullCaptureProvider implements CaptureProvider {
  async captureSignature(): Promise<string | null> {
    return null;
  }

  async capturePhoto(): Promise<string | null> {
    return null;
  }
}

/** طبقِ تصمیمِ اجرا زیرِ Expo Go (R187): expo-image-picker خودش رابطِ
 * کاملِ دوربینِ نیتیو را نشان می‌دهد و با Promise برمی‌گردد -- دقیقاً
 * هم‌راستا با همین اینترفیس، بدونِ نیاز به هیچ کامپوننتِ React جداگانه.
 *
 * امضا (captureSignature) برخلافِ دوربین رابطِ تمام‌صفحه‌یِ نیتیوِ خودش
 * را ندارد -- نیازمندِ یک کانواسِ لمسیِ دائمی در درختِ کامپوننت است، نه
 * یک تابعِ Promise-based ساده. راه‌حل (R191): requestSignature از
 * SignaturePadProvider (signature/SignaturePadProvider.tsx) از بیرون
 * تزریق می‌شود -- همان پُلِ لازم بینِ این کلاسِ سادهٔ غیرِReact و یک
 * Modal/کانواسِ واقعی. */
export class ExpoCaptureProvider implements CaptureProvider {
  constructor(private readonly requestSignature?: () => Promise<string | null>) {}

  async captureSignature(): Promise<string | null> {
    if (!this.requestSignature) return null;
    return this.requestSignature();
  }

  async capturePhoto(): Promise<string | null> {
    try {
      const permission = await ImagePicker.requestCameraPermissionsAsync();
      if (!permission.granted) return null;
      const result = await ImagePicker.launchCameraAsync({
        base64: true,
        quality: 0.6,
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
      });
      if (result.canceled) return null;
      return result.assets[0]?.base64 ?? null;
    } catch {
      return null;
    }
  }
}
