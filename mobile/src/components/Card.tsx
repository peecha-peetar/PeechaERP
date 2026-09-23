import React from "react";
import { StyleSheet, TouchableOpacity, View, ViewStyle } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

interface CardProps {
  children: React.ReactNode;
  onPress?: () => void;
  style?: ViewStyle;
  testID?: string;
}

/** جعبه‌یِ پایه‌یِ همه‌یِ کارت‌هایِ اختصاصی (Customer/Visit/Product/
 * Order/Payment) -- سایه‌یِ ملایم به‌جایِ خطِ مرزیِ سنگین، طبقِ حسِ
 * «اپِ مدرن» نه فرمِ اداری. */
export function Card({ children, onPress, style, testID }: CardProps) {
  const { colors, spacing, radius } = useTheme();
  const content = (
    <View
      testID={testID}
      style={[
        styles.base,
        {
          backgroundColor: colors.surface,
          borderRadius: radius.lg,
          padding: spacing.lg,
          borderColor: colors.border,
        },
        style,
      ]}
    >
      {children}
    </View>
  );
  if (!onPress) return content;
  return (
    <TouchableOpacity activeOpacity={0.8} onPress={onPress}>
      {content}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  base: {
    borderWidth: StyleSheet.hairlineWidth,
    shadowColor: "#11131F",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 8,
    elevation: 2,
  },
});
