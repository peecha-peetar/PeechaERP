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
 * امضا (captureSignature) هنوز پیاده نشده: بر خلافِ دوربین (که رابطِ
 * تمام‌صفحه‌یِ خودش را دارد)، یک signature-pad نیازمندِ یک کانواسِ
 * لمسیِ دائمی در درختِ کامپوننت است، نه یک تابعِ Promise-based ساده --
 * یعنی همین معماریِ CaptureProvider (کلاسِ ساده بدونِ دسترسی به React)
 * برایِ آن کافی نیست؛ نیازمندِ یک بازطراحیِ جداست (مثلاً یک Context/Ref
 * که یک Modal را از بیرونِ کامپوننت باز کند). */
export class ExpoCaptureProvider implements CaptureProvider {
  async captureSignature(): Promise<string | null> {
    return null;
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
