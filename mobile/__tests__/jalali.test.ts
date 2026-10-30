import { formatJalaliDate, formatJalaliDateTime } from "../src/jalali";

describe("formatJalaliDate", () => {
  it("converts Nowruz (Gregorian 2024-03-20) to Jalali 1403/01/01", () => {
    expect(formatJalaliDate("2024-03-20")).toBe("۱۴۰۳/۰۱/۰۱");
  });

  it("pads single-digit month/day and uses Persian digits", () => {
    expect(formatJalaliDate("2024-06-17")).toBe("۱۴۰۳/۰۳/۲۸");
  });

  it("ignores a trailing time component instead of shifting the day via UTC parsing", () => {
    expect(formatJalaliDate("2024-06-17T23:59:59Z")).toBe("۱۴۰۳/۰۳/۲۸");
  });
});

describe("formatJalaliDateTime", () => {
  it("appends Persian-digit hour:minute after the Jalali date", () => {
    expect(formatJalaliDateTime("2024-06-17T08:05:00")).toBe("۱۴۰۳/۰۳/۲۸ ۰۸:۰۵");
  });

  it("falls back to date-only when there is no time part", () => {
    expect(formatJalaliDateTime("2024-06-17")).toBe("۱۴۰۳/۰۳/۲۸");
  });
});
