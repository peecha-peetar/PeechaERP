import React from "react";
import { Text, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";
import { Card } from "./Card";
import { StatusBadge } from "./StatusBadge";

export interface CustomerCardProps {
  code: string;
  name: string;
  distanceLabel?: string;
  balanceLabel?: string;
  isOverdue?: boolean;
  statusCode?: string;
  statusLabel?: string;
  onPress?: () => void;
}

export function CustomerCard({ code, name, distanceLabel, balanceLabel, isOverdue, statusCode, statusLabel, onPress }: CustomerCardProps) {
  const { colors, spacing, typography } = useTheme();
  return (
    <Card onPress={onPress}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
        <View style={{ flex: 1 }}>
          <Text style={[typography.bodyBold, { color: colors.textPrimary }]} numberOfLines={1}>
            {name}
          </Text>
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>
            {code}
            {distanceLabel ? ` · ${distanceLabel}` : ""}
          </Text>
        </View>
        {statusCode && statusLabel ? <StatusBadge statusCode={statusCode} label={statusLabel} /> : null}
      </View>
      {balanceLabel ? (
        <View style={{ flexDirection: "row", marginTop: spacing.sm }}>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>مانده: </Text>
          <Text style={[typography.numeric, { color: isOverdue ? colors.danger : colors.textSecondary }]}>{balanceLabel}</Text>
        </View>
      ) : null}
    </Card>
  );
}
