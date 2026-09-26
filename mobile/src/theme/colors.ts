/** پالتِ رنگیِ Peecha Field Sales -- طبقِ اصلِ صریحِ کاربر: این اپ نباید
 * حسِ نسخه‌یِ کوچک‌شده‌یِ ERP را بدهد؛ رنگ‌ها مدرن، ساده و لمس‌محورند
 * (نه رنگ‌بندیِ خاکستریِ فرم‌محورِ دسکتاپ). هر رنگِ معنایی (success/
 * warning/danger) هم برایِ وضعیت‌هایِ دامنه (Synced/Pending/Failed،
 * پرداخت‌شده/معوق) و هم برایِ Toast/Badge استفاده می‌شود -- تکِ منبعِ
 * حقیقتی تا رنگ در کامپوننت‌هایِ مختلف قاطی نشود. */

export interface ColorPalette {
  background: string;
  surface: string;
  surfaceAlt: string;
  border: string;
  textPrimary: string;
  textSecondary: string;
  textInverse: string;
  primary: string;
  primaryDark: string;
  primarySoft: string;
  success: string;
  successSoft: string;
  warning: string;
  warningSoft: string;
  danger: string;
  dangerSoft: string;
  info: string;
  infoSoft: string;
  overlay: string;
  skeleton: string;
}

export const lightColors: ColorPalette = {
  background: "#F5F6FA",
  surface: "#FFFFFF",
  surfaceAlt: "#F0F1F7",
  border: "#E4E6EF",
  textPrimary: "#1A1D29",
  textSecondary: "#6B7080",
  textInverse: "#FFFFFF",
  primary: "#4F46E5",
  primaryDark: "#3730A3",
  primarySoft: "#EEF0FD",
  success: "#16A34A",
  successSoft: "#E8F8EE",
  warning: "#D97706",
  warningSoft: "#FDF3E3",
  danger: "#DC2626",
  dangerSoft: "#FCEAEA",
  info: "#2563EB",
  infoSoft: "#E9F0FE",
  overlay: "rgba(17, 19, 31, 0.5)",
  skeleton: "#E7E8F0",
};

export const darkColors: ColorPalette = {
  background: "#0F1117",
  surface: "#1A1D29",
  surfaceAlt: "#232635",
  border: "#2E3244",
  textPrimary: "#F5F6FA",
  textSecondary: "#9BA0B3",
  textInverse: "#1A1D29",
  primary: "#7C74F1",
  primaryDark: "#4F46E5",
  primarySoft: "#262244",
  success: "#34D373",
  successSoft: "#123423",
  warning: "#F0A93C",
  warningSoft: "#3A2A11",
  danger: "#F0605A",
  dangerSoft: "#3A1616",
  info: "#5B9BFF",
  infoSoft: "#132A4A",
  overlay: "rgba(0, 0, 0, 0.6)",
  skeleton: "#2A2E3D",
};
