import { I18nManager } from "react-native";

/** طبقِ اصلِ صریح («RTL فارسی صحیح باشد»): بایدAndroid/iOS را در حالتِ
 * RTL واقعی بگذارد (نه فقطِ textAlign دستی رویِ هر متن). طبقِ رفتارِ
 * شناخته‌شده‌یِ خودِ React Native: اگر forceRTL برایِ اولین‌بار تغییر
 * کند، لایه‌یِ نیتیو نیاز به Reload (نه فقط رندرِ دوباره‌یِ JS) دارد --
 * اپ باید این تابع را در همان ابتدایِ index.js/App.tsx صدا بزند، پیش
 * از رندرِ هر UI ای. */
export function applyRtlLayout(): void {
  if (!I18nManager.isRTL) {
    I18nManager.allowRTL(true);
    I18nManager.forceRTL(true);
  }
}
