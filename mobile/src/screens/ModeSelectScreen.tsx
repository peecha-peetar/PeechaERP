import React from "react";
import { Text, View } from "react-native";
import { Button, Card } from "../components";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  /** طبقِ درخواستِ صریحِ کاربر («همون تنظیمِ مدیر... فقط زودتر و
   * واضح‌تر نشان بدهد» -> در نهایت «انتخابِ دستیِ خودِ ویزیتور»
   * انتخاب شد): این مقدار از تنظیماتِ کاربر در دسکتاپ می‌آید و فقط
   * به‌عنوانِ پیش‌فرضِ پیشنهادی برجسته می‌شود -- ویزیتور هنوز باید
   * صریحاً یکی را انتخاب کند، حتی اگر همیشه یک‌چیز را انتخاب کند. */
  suggestedMode: "VAN_SALES" | "PRE_SALES" | null;
  onSelect: (mode: "VAN_SALES" | "PRE_SALES") => void;
}

/** طبقِ درخواستِ صریحِ کاربر («کاربر اول برنامه انتخاب کنه پخش گرم و
 * سرد و کلاً پروسه‌هاشون جدا باشه»): این صفحه بلافاصله بعدِ ورود نشان
 * داده می‌شود -- پیش از هر صفحهٔ دیگری. برخلافِ نسخهٔ قبلی (که این
 * مقدار را فقط از دسکتاپ می‌خواند و اگر تنظیم نشده بود کاربر رویِ
 * «در حالِ بررسیِ تنظیماتِ سفارش...» گیر می‌کرد)، حالا خودِ ویزیتور هر
 * بار که وارد اپ می‌شود مسیر را انتخاب می‌کند -- چون ممکن است یک نفر
 * روزی پخشِ گرم و روزِ دیگر پخشِ سرد کار کند. */
export function ModeSelectScreen({ suggestedMode, onSelect }: Props) {
  const { colors, spacing, typography } = useTheme();
  return (
    <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg, gap: spacing.lg, justifyContent: "center" }}>
      <Text style={[typography.h2, { color: colors.textPrimary, textAlign: "center" }]}>امروز چه‌کار می‌کنید؟</Text>

      <Card style={{ padding: spacing.lg, gap: spacing.sm }}>
        <Text style={[typography.h3, { color: colors.textPrimary }]}>🚚 پخشِ گرم</Text>
        <Text style={[typography.body, { color: colors.textSecondary }]}>
          فروشِ خودرویی — فاکتورِ آنی، امضا/عکسِ رسیدِ تحویل، تسویهٔ همان‌لحظه.
        </Text>
        <Button
          label={suggestedMode === "VAN_SALES" ? "شروعِ پخشِ گرم (پیش‌فرضِ شما)" : "شروعِ پخشِ گرم"}
          onPress={() => onSelect("VAN_SALES")}
        />
      </Card>

      <Card style={{ padding: spacing.lg, gap: spacing.sm }}>
        <Text style={[typography.h3, { color: colors.textPrimary }]}>📋 پخشِ سرد</Text>
        <Text style={[typography.body, { color: colors.textSecondary }]}>
          فقط سفارش‌گیری — بدونِ فاکتورِ آنی؛ ادامه (تاییدِ انبار/توزین و تبدیل به فاکتور) در دسکتاپ انجام می‌شود.
        </Text>
        <Button
          label={suggestedMode === "PRE_SALES" ? "شروعِ پخشِ سرد (پیش‌فرضِ شما)" : "شروعِ پخشِ سرد"}
          variant="secondary"
          onPress={() => onSelect("PRE_SALES")}
        />
      </Card>
    </View>
  );
}
