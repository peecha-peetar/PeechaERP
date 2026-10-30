import React from "react";
import { Text, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";
import { Button } from "./Button";

interface EmptyStateProps {
  title: string;
  description?: string;
  actionLabel?: string;
  onPressAction?: () => void;
}

// طبقِ درخواستِ صریحِ کاربر («از ایکن‌ها استفاده نکن»): بدونِ گلیفِ
// تزئینی -- فقط عنوان/توضیح/دکمه.
export function EmptyState({ title, description, actionLabel, onPressAction }: EmptyStateProps) {
  const { colors, spacing, typography } = useTheme();
  return (
    <View style={{ alignItems: "center", justifyContent: "center", padding: spacing.xxl }}>
      <Text style={[typography.h3, { color: colors.textPrimary, marginBottom: spacing.xs }]}>{title}</Text>
      {description ? (
        <Text style={[typography.body, { color: colors.textSecondary, textAlign: "center", marginBottom: spacing.lg }]}>
          {description}
        </Text>
      ) : null}
      {actionLabel && onPressAction ? (
        <Button label={actionLabel} onPress={onPressAction} variant="secondary" fullWidth={false} />
      ) : null}
    </View>
  );
}
