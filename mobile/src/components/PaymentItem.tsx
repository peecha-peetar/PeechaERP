import React from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

const METHOD_LABEL: Record<string, string> = { CASH: "نقد", BANK: "کارت/انتقال", CHECK: "چک" };

export interface PaymentItemProps {
  method: "CASH" | "BANK" | "CHECK" | string;
  amountLabel: string;
  customerName: string;
  dateLabel: string;
  onPress?: () => void;
}

export function PaymentItem({ method, amountLabel, customerName, dateLabel, onPress }: PaymentItemProps) {
  const { colors, spacing, typography } = useTheme();
  return (
    <TouchableOpacity
      disabled={!onPress}
      onPress={onPress}
      activeOpacity={0.7}
      style={[styles.row, { paddingVertical: spacing.md, borderBottomColor: colors.border }]}
    >
      <View style={{ flex: 1 }}>
        <Text style={[typography.bodyBold, { color: colors.textPrimary }]} numberOfLines={1}>
          {customerName}
        </Text>
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>
          {METHOD_LABEL[method] ?? method} · {dateLabel}
        </Text>
      </View>
      <Text style={[typography.numeric, { color: colors.success }]}>{amountLabel}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", borderBottomWidth: StyleSheet.hairlineWidth },
});
