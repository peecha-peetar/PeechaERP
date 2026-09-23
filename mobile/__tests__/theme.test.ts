import { darkColors, lightColors } from "../src/theme/colors";
import { radius, spacing } from "../src/theme/spacing";
import { statusTone, toneColor } from "../src/theme/statusColors";

/** طبقِ محدودیتِ محیطِ توسعه (نبودِ Android SDK/Xcode): این‌ها فقط
 * منطقِ خالصِ توکن‌هایِ Design System را تست می‌کنند (رنگ/فاصله/نگاشتِ
 * وضعیت)، نه رندرِ واقعیِ کامپوننت‌هایِ RN -- هم‌الگو با بقیهٔ تست‌هایِ
 * این پروژه. */

describe("theme tokens", () => {
  it("پالتِ روشن و تیره هر دو همه‌یِ کلیدهایِ لازم را دارند", () => {
    const keys = Object.keys(lightColors).sort();
    expect(Object.keys(darkColors).sort()).toEqual(keys);
  });

  it("مقیاسِ فاصله‌ها صعودی است", () => {
    const values = Object.values(spacing);
    for (let i = 1; i < values.length; i++) {
      expect(values[i]).toBeGreaterThan(values[i - 1]);
    }
  });

  it("radius.pill بزرگ‌ترین مقدار است (برایِ Badge/SearchBarِ کاملاً گرد)", () => {
    expect(radius.pill).toBeGreaterThan(radius.xl);
  });
});

describe("statusTone / toneColor", () => {
  it("وضعیت‌هایِ موفق را success می‌داند", () => {
    expect(statusTone("SYNCED")).toBe("success");
    expect(statusTone("ACTIVE")).toBe("success");
    expect(statusTone("APPROVED")).toBe("success");
  });

  it("وضعیت‌هایِ خطرناک/معوق را danger می‌داند", () => {
    expect(statusTone("FAILED")).toBe("danger");
    expect(statusTone("OVERDUE")).toBe("danger");
    expect(statusTone("BLACKLISTED")).toBe("danger");
  });

  it("وضعیتِ ناشناخته neutral برمی‌گردد (بدونِ Crash)", () => {
    expect(statusTone("SOME_UNKNOWN_STATUS")).toBe("neutral");
  });

  it("toneColor برایِ هر tone یک جفتِ رنگِ متفاوت از پیش‌فرض برمی‌گرداند", () => {
    const success = toneColor("success", lightColors);
    const danger = toneColor("danger", lightColors);
    expect(success.fg).not.toBe(danger.fg);
    expect(success.bg).not.toBe(danger.bg);
  });
});
