import React from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";
import { StatusBadge } from "./StatusBadge";

export interface OrderItemProps {
  documentNo: string;
  customerName: string;
  dateLabel: string;
  totalAmountLabel: string;
  statusCode: string;
  statusLabel: string;
  onPress?: () => void;
}

/** ردیفِ فهرستِ سفارش‌ها/فاکتورها (نه Card جدا -- طبقِ الگویِ لیست‌هایِ
 * فشرده‌تر برایِ فهرستِ بلند، برخلافِ CustomerCard/VisitCard که تکی/کم
 * تعداد دیده می‌شوند). */
export function OrderItem({ documentNo, customerName, dateLabel, totalAmountLabel, statusCode, statusLabel, onPress }: OrderItemProps) {
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
          #{documentNo} · {dateLabel}
        </Text>
      </View>
      <View style={{ alignItems: "flex-end" }}>
        <Text style={[typography.numeric, { color: colors.textPrimary }]}>{totalAmountLabel}</Text>
        <View style={{ marginTop: spacing.xs }}>
          <StatusBadge statusCode={statusCode} label={statusLabel} />
        </View>
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", borderBottomWidth: StyleSheet.hairlineWidth },
});
