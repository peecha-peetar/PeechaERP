# jasper-runner

موتورِ چاپِ حرفه‌ایِ گزارش‌ها -- طبقِ تصمیمِ معماری، JasperReports
(کتابخانه‌یِ Java، LGPLv3، رایگان) فقط چیدمان/خروجی (PDF/Excel) را انجام
می‌دهد؛ منطقِ محاسباتی (رول‌آپِ تراز، بهایِ تمام‌شده، فرمتِ اعشار/جلالی، ...)
همیشه در `reports.py`/`inventory_engine.py`/`numerals.py` می‌ماند و از
پایتون آماده (به‌صورتِ JSON) به این ابزار داده می‌شود.

`src/peecha/reporting/jasper_bridge.py` این جار را با `subprocess` صدا
می‌زند -- هیچ JVMای داخلِ خودِ اپِ Python بالا نمی‌آید.

## پیش‌نیاز برایِ Build

- JDK 17 یا بالاتر
- Apache Maven

## قدم‌هایِ Build

۱. فونتِ Vazirmatn را (مجوزِ OFL: https://github.com/rastikerdar/vazirmatn)
   در `src/main/resources/fonts/` با همین دو نام قرار بده (طبقِ همان
   قراردادِ `assets/fonts/README.md` -- باینریِ فونت عمداً در گیت کامیت
   نشده):

   ```
   src/main/resources/fonts/Vazirmatn-Regular.ttf
   src/main/resources/fonts/Vazirmatn-Bold.ttf
   ```

۲. از همین پوشه (`tools/jasper-runner/`):

   ```
   mvn -q package
   ```

   خروجی: `target/jasper-runner.jar` (fat-jar شاملِ JasperReports +
   وابستگی‌هایش -- برایِ اجرا فقط `java -jar` لازم است، Maven/اینترنت در
   زمانِ اجرا نیازی نیست).

`jasper_bridge.py` مسیرِ همین `target/jasper-runner.jar` را جست‌وجو می‌کند؛
اگر build نشده باشد، دکمه‌یِ «چاپِ حرفه‌ای» با پیامی روشن (نه کرش) به
همین راهنما ارجاع می‌دهد.

## چرا نسخه‌یِ ۶.۲۱.۳ (نه آخرین نسخه)

طیِ آزمایشِ مستقیم، JasperReports **۷.۰.۱** موتورِ بارگذاریِ JRXMLاش را
به‌طورِ کامل به Jackson تغییر داده و دیگر فرمتِ کلاسیکِ JRXML (با تگِ
`<band>` و namespace استاندارد -- همانی که Jaspersoft Studio تولید
می‌کند) را نمی‌شناسد. **۶.۲۱.۳** یک نسخه‌یِ پایدار و رایج است که کاملاً با
خروجیِ استانداردِ Jaspersoft Studio سازگار است -- طراحیِ گزارش‌ها باید با
همین نسخه (یا نسخه‌یِ ۶.x مشابه) در Jaspersoft Studio انجام شود.

## طراحیِ فونت

فونت با یک «Font Extension» (`src/main/resources/jasperreports_extension.properties`
+ `src/main/resources/fonts/peecha-fonts.xml`) به‌عنوانِ خانواده‌یِ
`Vazirmatn` سراسری معرفی شده -- در JRXML فقط کافی است
`<font fontName="Vazirmatn"/>` نوشته شود (یا از یک style پیش‌فرض با همین
fontName استفاده شود)، بدونِ نیازِ به تکرارِ pdfFontName/pdfEncoding/
isPdfEmbedded رویِ هر المان.

## استفاده‌یِ CLI

```
java -jar target/jasper-runner.jar <jrxml> <rows.json> <params.json> <output> <pdf|xlsx>
```

- `rows.json`: `{"rows": [ {...}, {...} ]}`
- `params.json`: نگاشتِ تخت از رشته‌ها برایِ پارامترهایِ گزارش
