/** طبقِ محدودیتِ محیطِ توسعه (نبودِ Android SDK/Xcode در سندباکسِ فعلی):
 * فقط منطقِ خالصِ TypeScript (سینک/صف‌ی آفلاین/کلاینتِ API) با ts-jest
 * تست می‌شود -- نه رندرِ واقعیِ کامپوننت‌هایِ RN رویِ دستگاه/شبیه‌ساز. */
module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  testMatch: ["**/__tests__/**/*.test.ts"],
};
