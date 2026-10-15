import React, { useState } from "react";
import { StyleSheet, Text, TextInput, TextInputProps, View, ViewStyle } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

interface InputProps extends Omit<TextInputProps, "style"> {
  label?: string;
  error?: string;
  numeric?: boolean;
  /** رویِ ظرفِ بیرونی اعمال می‌شود (مثلاً width برایِ فیلدهایِ کوچکِ
   * کنارِهم در یک ردیف) -- نه رویِ خودِ TextInput، تا استایلِ داخلیِ
   * ثابت (رنگ/ارتفاع/حاشیه) از بیرون بازنویسی نشود. */
  style?: ViewStyle;
}

export function Input({ label, error, numeric, style, ...rest }: InputProps) {
  const { colors, spacing, radius, typography } = useTheme();
  const [focused, setFocused] = useState(false);

  return (
    <View style={[{ marginBottom: spacing.md }, style]}>
      {label ? <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }]}>{label}</Text> : null}
      <TextInput
        {...rest}
        onFocus={(e) => {
          setFocused(true);
          rest.onFocus?.(e);
        }}
        onBlur={(e) => {
          setFocused(false);
          rest.onBlur?.(e);
        }}
        placeholderTextColor={colors.textSecondary}
        style={[
          numeric ? typography.numeric : typography.body,
          {
            color: colors.textPrimary,
            backgroundColor: colors.surfaceAlt,
            borderRadius: radius.md,
            paddingHorizontal: spacing.md,
            height: 48,
            borderWidth: 1.5,
            borderColor: error ? colors.danger : focused ? colors.primary : "transparent",
          },
        ]}
      />
      {error ? <Text style={[typography.caption, { color: colors.danger, marginTop: spacing.xs }]}>{error}</Text> : null}
    </View>
  );
}
