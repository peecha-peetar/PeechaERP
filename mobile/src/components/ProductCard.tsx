import React from "react";
import { Text, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";
import { Card } from "./Card";

export interface ProductCardProps {
  code: string;
  name: string;
  uomLabel: string;
  unitPrice?: string;
  stockQuantity?: string;
  quantity?: number;
  onIncrease?: () => void;
  onDecrease?: () => void;
  onPress?: () => void;
}

/** طبقِ اصلِ «سریع‌ترین قسمتِ برنامه» (سفارش‌گیری، Phase 4): افزایش/
 * کاهشِ تعداد مستقیم رویِ خودِ کارت، بدونِ بازکردنِ صفحه/دیالوگِ جدا. */
export function ProductCard({ code, name, uomLabel, unitPrice, stockQuantity, quantity, onIncrease, onDecrease, onPress }: ProductCardProps) {
  const { colors, spacing, typography, radius } = useTheme();
  return (
    <Card onPress={onPress} style={{ padding: spacing.md }}>
      <View style={{ flexDirection: "row", alignItems: "center" }}>
        <View style={{ flex: 1 }}>
          <Text style={[typography.bodyBold, { color: colors.textPrimary }]} numberOfLines={1}>
            {name}
          </Text>
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>
            {code} · {uomLabel}
            {stockQuantity !== undefined ? ` · موجودی ${stockQuantity}` : ""}
          </Text>
          {unitPrice ? <Text style={[typography.numeric, { color: colors.primary, marginTop: spacing.xs }]}>{unitPrice}</Text> : null}
        </View>
        {onIncrease && onDecrease ? (
          <View style={{ flexDirection: "row", alignItems: "center", backgroundColor: colors.surfaceAlt, borderRadius: radius.pill }}>
            <QtyButton label="−" onPress={onDecrease} />
            <Text style={[typography.numeric, { color: colors.textPrimary, minWidth: 24, textAlign: "center" }]}>{quantity ?? 0}</Text>
            <QtyButton label="+" onPress={onIncrease} />
          </View>
        ) : null}
      </View>
    </Card>
  );
}

function QtyButton({ label, onPress }: { label: string; onPress: () => void }) {
  const { colors } = useTheme();
  return (
    <Text
      onPress={onPress}
      accessibilityRole="button"
      style={{ color: colors.primary, fontSize: 20, fontWeight: "700", paddingHorizontal: 12, paddingVertical: 4 }}
    >
      {label}
    </Text>
  );
}
