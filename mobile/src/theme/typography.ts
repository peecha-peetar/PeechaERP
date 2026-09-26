import { TextStyle } from "react-native";

/** تایپوگرافیِ فارسی/RTL -- طبقِ درخواستِ صریحِ کاربر، فونتِ Vazirmatn
 * (assets/fonts/*.ttf، از پکیجِ npm رسمیِ vazirmatn، مجوزِ SIL OFL).
 *
 * طبقِ محدودیتِ شناخته‌شده‌یِ فونت‌هایِ استاتیکِ سفارشی در React Native:
 * روی اندروید، fontWeight رویِ یک fontFamilyِ سفارشی سینتز نمی‌شود (فقط
 * برایِ فونتِ سیستم کار می‌کند) -- روشِ درست این است که هر وزن، خودش یک
 * fontFamilyِ جداگانه باشد (Vazirmatn-Regular/SemiBold/Bold) و fontWeight
 * اصلاً ست نشود. کپیِ واقعیِ فایل‌هایِ فونت به پروژه‌یِ نیتیو هنوز نیازمندِ
 * یک‌بار اجرایِ `npx react-native-asset` رویِ ماشینِ دارایِ Android
 * SDK/Xcode است (react-native.config.js همین الان آماده است). */

const VAZIRMATN_REGULAR = "Vazirmatn-Regular";
const VAZIRMATN_SEMIBOLD = "Vazirmatn-SemiBold";
const VAZIRMATN_BOLD = "Vazirmatn-Bold";

interface TextVariant extends TextStyle {}

export const typography: Record<
  "h1" | "h2" | "h3" | "body" | "bodyBold" | "caption" | "captionBold" | "button" | "numeric",
  TextVariant
> = {
  h1: { fontFamily: VAZIRMATN_BOLD, fontSize: 24, writingDirection: "rtl", textAlign: "right" },
  h2: { fontFamily: VAZIRMATN_BOLD, fontSize: 20, writingDirection: "rtl", textAlign: "right" },
  h3: { fontFamily: VAZIRMATN_SEMIBOLD, fontSize: 17, writingDirection: "rtl", textAlign: "right" },
  body: { fontFamily: VAZIRMATN_REGULAR, fontSize: 15, writingDirection: "rtl", textAlign: "right" },
  bodyBold: { fontFamily: VAZIRMATN_BOLD, fontSize: 15, writingDirection: "rtl", textAlign: "right" },
  caption: { fontFamily: VAZIRMATN_REGULAR, fontSize: 12, writingDirection: "rtl", textAlign: "right" },
  captionBold: { fontFamily: VAZIRMATN_BOLD, fontSize: 12, writingDirection: "rtl", textAlign: "right" },
  button: { fontFamily: VAZIRMATN_BOLD, fontSize: 15, writingDirection: "rtl", textAlign: "center" },
  // اعدادِ پول/تعداد همیشه LTR بمانند بهتر است (مبلغ/شماره‌یِ چند رقمی
  // در RTL به‌هم‌ریخته نمایش داده می‌شود) -- طبقِ رفتارِ استانداردِ
  // اپ‌هایِ فارسی/عربی برایِ اعداد.
  numeric: { fontFamily: VAZIRMATN_BOLD, fontSize: 15, writingDirection: "ltr", textAlign: "left" },
};
