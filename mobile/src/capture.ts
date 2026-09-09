/** انتزاعِ گرفتنِ امضا/عکسِ رسیدِ تحویل -- در اپِ واقعی با یک کتابخانه‌یِ
 * نیتیوِ signature-pad و دوربین پیاده می‌شود (قابلِ‌نصب/تست در این
 * سندباکسِ بدونِ Android SDK/Xcode نیست). خروجی طبقِ قراردادِ
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
