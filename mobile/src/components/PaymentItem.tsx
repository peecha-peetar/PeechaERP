import React from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

const METHOD_ICON: Record<string, string> = { CASH: "💵", BANK: "💳", CHECK: "📄" };
const METHOD_LABEL: Record<string, string> = { CASH: "نقد", BANK: "کارت/انتقال", CHECK: "چک" };

export interface PaymentItemProps {
  method: "CASH" | "BANK" | "CHECK" | string;
  amountLabel: string;
  customerName: string;
  dateLabel: string;
  onPress?: () => void;
}

export function PaymentItem({ method, amountLabel, customerName, dateLabel, onPress }: PaymentItemProps) {
  const { colors, spacing, typography, radius } = useTheme();
  return (
    <TouchableOpacity
      disabled={!onPress}
      onPress={onPress}
      activeOpacity={0.7}
      style={[styles.row, { paddingVertical: spacing.md, borderBottomColor: colors.border }]}
    >
      <View style={[styles.iconWrap, { backgroundColor: colors.successSoft, borderRadius: radius.md }]}>
        <Text style={{ fontSize: 18 }}>{METHOD_ICON[method] ?? "💰"}</Text>
      </View>
      <View style={{ flex: 1, marginStart: spacing.sm }}>
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
  iconWrap: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
});
