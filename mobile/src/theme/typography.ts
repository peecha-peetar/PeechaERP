import { TextStyle } from "react-native";

/** تایپوگرافیِ فارسی/RTL -- طبقِ محدودیتِ شناخته‌شده: در این سندباکس
 * فونتِ فارسیِ اختصاصی (مثلِ Vazirmatn/IRANSans) قابلِ‌باندل‌کردن نیست
 * (نیازمندِ فایلِ فونت + لینکِ نیتیو)؛ فعلاً فونتِ سیستم با
 * writingDirection: "rtl" استفاده می‌شود -- افزودنِ فونتِ اختصاصی فقط
 * نیازمندِ تغییرِ fontFamily در همین یک فایل است، نه در صفحه‌ها. */

export const fontFamily = undefined; // TODO(UI-8): فونتِ فارسیِ اختصاصی

interface TextVariant extends TextStyle {}

export const typography: Record<
  "h1" | "h2" | "h3" | "body" | "bodyBold" | "caption" | "captionBold" | "button" | "numeric",
  TextVariant
> = {
  h1: { fontFamily, fontSize: 24, fontWeight: "700", writingDirection: "rtl", textAlign: "right" },
  h2: { fontFamily, fontSize: 20, fontWeight: "700", writingDirection: "rtl", textAlign: "right" },
  h3: { fontFamily, fontSize: 17, fontWeight: "600", writingDirection: "rtl", textAlign: "right" },
  body: { fontFamily, fontSize: 15, fontWeight: "400", writingDirection: "rtl", textAlign: "right" },
  bodyBold: { fontFamily, fontSize: 15, fontWeight: "700", writingDirection: "rtl", textAlign: "right" },
  caption: { fontFamily, fontSize: 12, fontWeight: "400", writingDirection: "rtl", textAlign: "right" },
  captionBold: { fontFamily, fontSize: 12, fontWeight: "700", writingDirection: "rtl", textAlign: "right" },
  button: { fontFamily, fontSize: 15, fontWeight: "700", writingDirection: "rtl", textAlign: "center" },
  // اعدادِ پول/تعداد همیشه LTR بمانند بهتر است (مبلغ/شماره‌یِ چند رقمی
  // در RTL به‌هم‌ریخته نمایش داده می‌شود) -- طبقِ رفتارِ استانداردِ
  // اپ‌هایِ فارسی/عربی برایِ اعداد.
  numeric: { fontFamily, fontSize: 15, fontWeight: "700", writingDirection: "ltr", textAlign: "left" },
};
