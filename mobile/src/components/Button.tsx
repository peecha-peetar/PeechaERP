import React from "react";
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, ViewStyle } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
export type ButtonSize = "md" | "lg";

interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  size?: ButtonSize;
  disabled?: boolean;
  loading?: boolean;
  fullWidth?: boolean;
  icon?: React.ReactNode;
  style?: ViewStyle;
  testID?: string;
}

/** طبقِ اصلِ «کمترین تعداد کلیک، لمس‌محور»: ارتفاعِ لمسیِ حداقل ۴۸ (lg)
 * تا برایِ استفاده‌یِ یک‌دستیِ ویزیتور در حینِ راه‌رفتن مناسب باشد. */
export function Button({
  label,
  onPress,
  variant = "primary",
  size = "lg",
  disabled = false,
  loading = false,
  fullWidth = true,
  icon,
  style,
  testID,
}: ButtonProps) {
  const { colors, spacing, radius, typography } = useTheme();
  const isDisabled = disabled || loading;

  const backgroundColor = {
    primary: colors.primary,
    secondary: colors.surfaceAlt,
    danger: colors.danger,
    ghost: "transparent",
  }[variant];

  const textColor = {
    primary: colors.textInverse,
    secondary: colors.textPrimary,
    danger: colors.textInverse,
    ghost: colors.primary,
  }[variant];

  const height = size === "lg" ? 52 : 44;

  return (
    <TouchableOpacity
      testID={testID}
      accessibilityRole="button"
      accessibilityState={{ disabled: isDisabled }}
      onPress={onPress}
      disabled={isDisabled}
      activeOpacity={0.75}
      style={[
        styles.base,
        {
          backgroundColor,
          height,
          borderRadius: radius.md,
          paddingHorizontal: spacing.lg,
          opacity: isDisabled ? 0.5 : 1,
          alignSelf: fullWidth ? "stretch" : "flex-start",
        },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={textColor} />
      ) : (
        <>
          {icon}
          <Text style={[typography.button, { color: textColor, marginStart: icon ? spacing.sm : 0 }]}>{label}</Text>
        </>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  base: { flexDirection: "row", alignItems: "center", justifyContent: "center" },
});
