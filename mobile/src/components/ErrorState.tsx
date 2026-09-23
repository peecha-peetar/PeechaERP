import React from "react";
import { Text, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";
import { Button } from "./Button";

interface ErrorStateProps {
  title?: string;
  description?: string;
  retryLabel?: string;
  onRetry?: () => void;
}

/** طبقِ اصلِ صریح («هنگامِ قطعِ اینترنت UI Crash نکند»): این کامپوننت
 * برایِ همه‌یِ خطاهایِ شبکه/سرور استفاده می‌شود، نه پیامِ خامِ Exception. */
export function ErrorState({
  title = "مشکلی پیش آمد",
  description = "اتصال را بررسی کنید و دوباره تلاش کنید.",
  retryLabel = "تلاشِ دوباره",
  onRetry,
}: ErrorStateProps) {
  const { colors, spacing, typography } = useTheme();
  return (
    <View style={{ alignItems: "center", justifyContent: "center", padding: spacing.xxl }}>
      <Text style={{ fontSize: 40, marginBottom: spacing.md }}>⚠️</Text>
      <Text style={[typography.h3, { color: colors.textPrimary, marginBottom: spacing.xs }]}>{title}</Text>
      <Text style={[typography.body, { color: colors.textSecondary, textAlign: "center", marginBottom: spacing.lg }]}>
        {description}
      </Text>
      {onRetry ? <Button label={retryLabel} onPress={onRetry} variant="secondary" fullWidth={false} /> : null}
    </View>
  );
}
