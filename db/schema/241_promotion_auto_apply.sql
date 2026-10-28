-- پیچا | R353: اعمال خودکار پروموشن در فروش حضوری (پیش از تسویه) و سفارش موبایل (در سرور)
INSERT INTO comm.feature_definitions (feature_code, name, module_scope, requires_feature_code, requires_account_mapping_keys)
VALUES ('PROMOTION_AUTO_APPLY', 'اعمال خودکار پروموشن در فروش حضوری و سفارش برنامهٔ موبایل', 'COMMERCIAL', NULL, NULL)
ON CONFLICT (feature_code) DO NOTHING;
