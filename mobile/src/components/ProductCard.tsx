import React from "react";
import { Image, Text, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";
import { Card } from "./Card";

export interface ProductCardProps {
  code: string;
  name: string;
  uomLabel: string;
  unitPrice?: string;
  stockQuantity?: string;
  quantity?: number;
  /** JPEGِ کوچک‌شده‌یِ Base64 (بدونِ پیشوندِ data:) -- طبقِ درخواستِ صریحِ
   * کاربر («عکسِ کالاهایِ تعریف‌شده در کاتالوگ بیاد خیلی انگشتی»). */
  photoBase64?: string | null;
  onIncrease?: () => void;
  onDecrease?: () => void;
  onPress?: () => void;
}

/** طبقِ اصلِ «سریع‌ترین قسمتِ برنامه» (سفارش‌گیری، Phase 4): افزایش/
 * کاهشِ تعداد مستقیم رویِ خودِ کارت، بدونِ بازکردنِ صفحه/دیالوگِ جدا. */
export function ProductCard({ code, name, uomLabel, unitPrice, stockQuantity, quantity, photoBase64, onIncrease, onDecrease, onPress }: ProductCardProps) {
  const { colors, spacing, typography, radius } = useTheme();
  return (
    <Card onPress={onPress} style={{ padding: spacing.md }}>
      <View style={{ flexDirection: "row", alignItems: "center" }}>
        {photoBase64 ? (
          <Image
            source={{ uri: `data:image/jpeg;base64,${photoBase64}` }}
            style={{ width: 44, height: 44, borderRadius: radius.sm, marginLeft: spacing.sm, backgroundColor: colors.surfaceAlt }}
            resizeMode="cover"
          />
        ) : null}
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
  const { colors, typography } = useTheme();
  return (
    <Text
      onPress={onPress}
      accessibilityRole="button"
      style={[typography.bodyBold, { color: colors.primary, fontSize: 20, textAlign: "center", paddingHorizontal: 12, paddingVertical: 4 }]}
    >
      {label}
    </Text>
  );
}
