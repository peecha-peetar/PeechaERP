-- پیچا | طراحِ بصریِ گزارشِ چاپی (WYSIWYG، مثلِ FastReport) — روی همان
-- منبعِ داده‌یِ گزارش‌سازِ کامل (acc.report_templates، فایلِ 019) سوار
-- می‌شود: به‌جایِ جدولِ ثابت، کاربر با ماوس متن/فیلد/خط/مستطیل/تصویر را
-- در باندهایِ هدر/جزئیات/فوتر جابجا و اندازه‌دهی می‌کند.
-- پیش‌نیاز: 019_report_designer.sql

CREATE TABLE acc.visual_report_templates (
    visual_template_id SERIAL      NOT NULL PRIMARY KEY,
    company_id           INT       NOT NULL REFERENCES core.companies(company_id),
    name                  VARCHAR(200) NOT NULL,
    report_template_id    INT      NOT NULL REFERENCES acc.report_templates(report_template_id),
    page_size              VARCHAR(10) NOT NULL DEFAULT 'A4',
    orientation             VARCHAR(10) NOT NULL DEFAULT 'PORTRAIT' CHECK (orientation IN ('PORTRAIT', 'LANDSCAPE')),
    margin_top_mm           NUMERIC(6, 2) NOT NULL DEFAULT 15,
    margin_bottom_mm        NUMERIC(6, 2) NOT NULL DEFAULT 15,
    margin_left_mm          NUMERIC(6, 2) NOT NULL DEFAULT 15,
    margin_right_mm         NUMERIC(6, 2) NOT NULL DEFAULT 15,
    -- گروه‌بندی فقط برایِ report_templateهایِ DETAIL با group_by_account=TRUE
    -- معنا دارد (رویِ همان مکانیزمِ ردیف‌هایِ جمعِ فرعیِ موجود سوار می‌شود،
    -- نه یک موتورِ گروه‌بندیِ تازه)؛ اگر فعال باشد، باندهایِ GROUP_HEADER/
    -- GROUP_FOOTER هم رندر می‌شوند.
    use_grouping             BOOLEAN NOT NULL DEFAULT FALSE,
    display_order            INT     NOT NULL DEFAULT 0
);

CREATE TABLE acc.visual_report_bands (
    band_id             SERIAL   NOT NULL PRIMARY KEY,
    visual_template_id  INT      NOT NULL REFERENCES acc.visual_report_templates(visual_template_id) ON DELETE CASCADE,
    band_type            VARCHAR(20) NOT NULL CHECK (band_type IN (
        'REPORT_HEADER', 'PAGE_HEADER', 'GROUP_HEADER', 'DETAIL',
        'GROUP_FOOTER', 'PAGE_FOOTER', 'REPORT_FOOTER'
    )),
    height_mm             NUMERIC(6, 2) NOT NULL DEFAULT 10,
    UNIQUE (visual_template_id, band_type)
);

CREATE TABLE acc.visual_report_objects (
    object_id     SERIAL   NOT NULL PRIMARY KEY,
    band_id        INT      NOT NULL REFERENCES acc.visual_report_bands(band_id) ON DELETE CASCADE,
    object_type     VARCHAR(20) NOT NULL CHECK (object_type IN ('TEXT', 'FIELD', 'LINE', 'RECTANGLE', 'IMAGE')),
    x_mm             NUMERIC(6, 2) NOT NULL,
    y_mm             NUMERIC(6, 2) NOT NULL,
    width_mm         NUMERIC(6, 2) NOT NULL,
    height_mm        NUMERIC(6, 2) NOT NULL,
    -- TEXT: متنِ ثابت. FIELD: field_code از کاتالوگِ گزارشِ تراکنشی، یا
    -- "ROW_LABEL"/"COL_<n>" برایِ گزارشِ خلاصه، یا یکی از فیلدهایِ ویژه‌ی
    -- سراسری (COMPANY_NAME/REPORT_TITLE/PRINT_DATE/PAGE_NUMBER/PAGE_COUNT/
    -- GRAND_TOTAL_DEBIT/GRAND_TOTAL_CREDIT) که در هر باندی مجازند.
    text_content      TEXT,
    field_code        VARCHAR(30),
    font_family       VARCHAR(50) NOT NULL DEFAULT 'default',
    font_size         SMALLINT NOT NULL DEFAULT 10,
    font_bold         BOOLEAN NOT NULL DEFAULT FALSE,
    text_align        VARCHAR(10) NOT NULL DEFAULT 'RIGHT' CHECK (text_align IN ('RIGHT', 'CENTER', 'LEFT')),
    border_style      VARCHAR(10) NOT NULL DEFAULT 'NONE' CHECK (border_style IN ('NONE', 'ALL', 'BOTTOM', 'TOP')),
    image_data        BYTEA
);
CREATE INDEX ix_visual_report_objects_band ON acc.visual_report_objects(band_id);
