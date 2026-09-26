/** مقیاسِ فاصله‌ها -- طبقِ اصلِ ۸پیکسلی، تا کارت/دکمه/فاصله‌یِ صفحه‌ها
 * در همه‌یِ صفحاتِ بعدی یکدست بماند (نه هرکس هرچه خواست بنویسد). */
export const spacing = {
  xxs: 2,
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
} as const;

export type SpacingKey = keyof typeof spacing;

export const radius = {
  sm: 6,
  md: 10,
  lg: 16,
  xl: 24,
  pill: 999,
} as const;

export type RadiusKey = keyof typeof radius;
