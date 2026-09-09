-- طبقِ بازخوردِ صریحِ کاربر («امکاناتِ حیاتیِ PeechaSync -- Smart Publish»):
-- تنظیماتِ پردازشِ خودکارِ تصویرِ محصول (واترمارک، حکِ کدِ کالا، فشرده‌
-- سازی/WebP) -- یک ردیف به‌ازایِ هر شرکت، هم‌الگو با ai_content_settings.
CREATE TABLE comm.smart_publish_settings (
    company_id INT PRIMARY KEY REFERENCES core.companies(company_id),
    watermark_storage_key VARCHAR(500) NULL,
    watermark_opacity NUMERIC(4,3) NOT NULL DEFAULT 0.5,
    watermark_scale NUMERIC(4,3) NOT NULL DEFAULT 0.2,
    watermark_position VARCHAR(20) NOT NULL DEFAULT 'bottom-right'
        CHECK (watermark_position IN ('bottom-right', 'bottom-left', 'top-right', 'top-left', 'center')),
    stamp_text_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    stamp_text_source VARCHAR(20) NOT NULL DEFAULT 'item_code'
        CHECK (stamp_text_source IN ('item_code', 'item_name')),
    webp_quality INT NOT NULL DEFAULT 80
);
