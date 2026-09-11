# دیتایِ نمونه برایِ پیش‌نمایش در Jaspersoft Studio

هر قالبِ گزارش (`../*.jrxml`) با دیتایِ واقعی از طریقِ `jasper-runner.jar`
(نه از داخلِ خودِ Studio) پر می‌شود -- یعنی وقتی فایلِ jrxml را مستقیم در
Jaspersoft Studio باز می‌کنید، دکمه‌یِ Preview به‌تنهایی دیتایی برایِ نمایش
ندارد. برایِ این‌که بتوانید حینِ طراحی، گزارش را با دیتایِ فارسیِ واقعی
ببینید، این پوشه یک جفت فایلِ `<نام>_rows.json` و `<نام>_params.json`
برایِ هر قالب دارد.

## راه‌اندازیِ Data Adapter در Studio (یک‌بار، برایِ هر قالب)

۱. در Jaspersoft Studio، از منویِ **Window → Show View → Repository Explorer**
   (یا از پنلِ Data Adapters هنگامِ کلیک رویِ Preview) گزینه‌یِ
   **Create Data Adapter** را بزنید.
۲. نوعِ **JSON File Datasource** (یا **JSON QL Datasource**، بسته به
   نسخه‌یِ Studio) را انتخاب کنید.
۳. در فیلدِ **JSON Source**، فایلِ `<نام>_rows.json` را انتخاب کنید
   (مثلاً `kardex_rows.json` برایِ `kardex.jrxml`).
۴. اگر Studio فیلدِ **Select expression / Query String** خواست، مقدارِ
   `rows` را وارد کنید (چون ساختارِ فایل `{"rows": [...]}` است).
۵. ذخیره کنید و رویِ دکمه‌یِ **Preview** بزنید -- گزارش با همین دیتایِ
   نمونه (که ساختارش دقیقاً با چیزی که برنامه در زمانِ اجرا می‌فرستد یکی
   است) نمایش داده می‌شود.

## پارامترها

فایلِ `<نام>_params.json` مقادیرِ نمونه‌یِ پارامترهایِ همان گزارش (نامِ
شرکت، بازه‌یِ تاریخ، جمع‌هایِ کل، ...) را دارد. در پنجره‌یِ Preview، Studio
یک فرم برایِ واردکردنِ پارامترها نشان می‌دهد -- می‌توانید مقادیر را از
همین فایل کپی کنید (یا اگر نسخه‌یِ Studio اجازه‌یِ Import از JSON را
می‌دهد، از همان استفاده کنید).

## نکته‌یِ مهم دربارهٔ افزودنِ فیلدِ جدید

اگر در حینِ طراحی یک فیلدِ جدید به گزارش اضافه کردید، حتماً یک
`<property name="net.sf.jasperreports.json.field.expression" value="نامِ_فیلد"/>`
هم به همان `<field>` اضافه کنید (قبل از `<fieldDescription>`، طبقِ
ترتیبِ اسکیمای jrxml) -- در غیرِ این صورت، در زمانِ اجرایِ واقعی (که از
طریقِ jasper-runner.jar و نه Studio است)، اگر برایِ آن فیلد برچسبِ فارسی
هم گذاشته باشید، مقدارش «null» می‌شود (چونِ JsonDataSourceِ کلاسیک در
نبودِ این property، از خودِ برچسبِ فارسی به‌عنوانِ مسیرِ استخراجِ JSON
استفاده می‌کند). نمونه‌ی درست:

```xml
<field name="my_new_field" class="java.lang.String">
    <property name="net.sf.jasperreports.json.field.expression" value="my_new_field"/>
    <fieldDescription><![CDATA[برچسبِ فارسیِ من]]></fieldDescription>
</field>
```

و در سمتِ پایتون (`_build_jasper_rows_and_params` در همان صفحه)، کلیدِ
دیکشنری هم باید دقیقاً همان `my_new_field` باشد.
