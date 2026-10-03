import React from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

interface SearchBarProps {
  value: string;
  onChangeText: (text: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}

/** طبقِ اصلِ صریح («Search مشتری سریع و قابلِ‌استفاده باشد»): بدونِ
 * دکمه‌یِ جداگانه‌یِ جستجو -- فیلترِ آنیِ روی هر کیبورد، مناسبِ جستجویِ
 * سریعِ کالا/مشتری در حینِ ویزیت. */
export function SearchBar({ value, onChangeText, placeholder = "جستجو...", autoFocus }: SearchBarProps) {
  const { colors, spacing, radius, typography } = useTheme();
  return (
    <View
      style={[
        styles.container,
        { backgroundColor: colors.surfaceAlt, borderRadius: radius.pill, paddingHorizontal: spacing.lg },
      ]}
    >
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.textSecondary}
        autoFocus={autoFocus}
        style={[typography.body, { color: colors.textPrimary, flex: 1, height: 44 }]}
      />
      {value.length > 0 ? (
        <Text onPress={() => onChangeText("")} style={[typography.caption, { color: colors.textSecondary, padding: spacing.xs }]}>
          پاک
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flexDirection: "row", alignItems: "center" },
});
