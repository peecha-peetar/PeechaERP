-- طبقِ درخواستِ صریح («تولیدِ محتوایِ خودکار با هوش مصنوعی»): کلیدِ
-- APIِ Geminiِ هر شرکت -- هم‌الگو با اعتبارِ رمزنگاری‌شده‌یِ اتصال‌هایِ
-- فروشگاه/بات.
CREATE TABLE comm.ai_content_settings (
    company_id BIGINT PRIMARY KEY REFERENCES core.companies(company_id),
    api_key_encrypted BYTEA
);
