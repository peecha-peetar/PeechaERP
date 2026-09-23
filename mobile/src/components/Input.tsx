import React, { useState } from "react";
import { StyleSheet, Text, TextInput, TextInputProps, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

interface InputProps extends Omit<TextInputProps, "style"> {
  label?: string;
  error?: string;
  numeric?: boolean;
}

export function Input({ label, error, numeric, ...rest }: InputProps) {
  const { colors, spacing, radius, typography } = useTheme();
  const [focused, setFocused] = useState(false);

  return (
    <View style={{ marginBottom: spacing.md }}>
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
