/** فرمتِ سادهٔ مبلغ برایِ نمایش (جداکننده‌یِ هزارگان، LTR) -- طبقِ اصلِ
 * typography.numeric: مبلغ همیشه چپ‌به‌راست نمایش داده می‌شود. ورودی از
 * API رشته است (decimal.Decimal سمتِ سرور) تا خطایِ گردکردنِ اعشاریِ
 * float در جاوااسکریپت پیش نیاید؛ فقط همین‌جا، فقط برایِ نمایش، به عدد
 * تبدیل می‌شود. */
export function formatAmount(value: string): string {
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}
