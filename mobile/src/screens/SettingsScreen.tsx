import React from "react";
import { Text, View } from "react-native";
import { ApiClient } from "../api/client";
import { Button, Card } from "../components";
import { useTheme, useThemeControls } from "../theme";

interface Props {
  apiClient: ApiClient;
  userFullName: string;
  onLoggedOut: () => void;
  onBack: () => void;
  onOpenManagerDashboard: () => void;
}

/** طبقِ اصلِ صریح («Dark/Light Theme»): سوییچِ دستیِ تم + خروجِ حساب --
 * حداقلیِ لازم برایِ UI-7؛ تنظیماتِ بیشتر (مثلِ اعلان‌هایِ Push) در
 * فازهایِ بعدی که خودِ آن قابلیت‌ها ساخته شوند اضافه می‌شود.
 *
 * دکمه‌یِ داشبوردِ مدیریت همیشه نشان داده می‌شود (اپِ موبایل نمی‌داند
 * کاربرِ فعلی مدیر است یا نه -- سرور خودش با ۴۰۳ تصمیم می‌گیرد، همان
 * الگویِ RBACِ لایه‌یِ API؛ ManagerDashboardScreen آن خطا را با پیامِ
 * روشن نشان می‌دهد، نه Crash). */
export function SettingsScreen({ apiClient, userFullName, onLoggedOut, onBack, onOpenManagerDashboard }: Props) {
  const { colors, spacing, typography, mode } = useTheme();
  const { toggleMode } = useThemeControls();

  const logout = async () => {
    await apiClient.logout();
    onLoggedOut();
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg, gap: spacing.lg }}>
      <Button label="← بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
      <Text style={[typography.h2, { color: colors.textPrimary }]}>تنظیمات</Text>

      <Card>
        <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>{userFullName}</Text>
      </Card>

      <Card>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <Text style={[typography.body, { color: colors.textPrimary }]}>پوسته‌یِ تیره</Text>
          <Button label={mode === "dark" ? "فعال ✓" : "غیرِفعال"} variant="secondary" fullWidth={false} onPress={toggleMode} />
        </View>
      </Card>

      <Button label="📊 داشبوردِ مدیریت" variant="secondary" onPress={onOpenManagerDashboard} />

      <Button label="خروج از حساب" variant="danger" onPress={logout} />
    </View>
  );
}
