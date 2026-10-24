import React from "react";
import { Text, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";
import { Card } from "./Card";

export type VisitCardState = "DONE" | "CURRENT" | "UPCOMING" | "SKIPPED";

export interface VisitCardProps {
  customerName: string;
  timeLabel?: string;
  distanceLabel?: string;
  state: VisitCardState;
  onPress?: () => void;
}

// طبقِ درخواستِ صریحِ کاربر («از ایکن‌ها استفاده نکن»): وضعیت با یک
// نقطه‌یِ رنگی -- نه یک نمادِ متنیِ تزئینی -- نشان داده می‌شود.
export function VisitCard({ customerName, timeLabel, distanceLabel, state, onPress }: VisitCardProps) {
  const { colors, spacing, typography } = useTheme();
  const stateColor = { DONE: colors.success, CURRENT: colors.primary, UPCOMING: colors.textSecondary, SKIPPED: colors.danger }[state];

  return (
    <Card onPress={onPress} style={{ paddingVertical: spacing.md }}>
      <View style={{ flexDirection: "row", alignItems: "center" }}>
        <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: stateColor }} />
        <View style={{ flex: 1, marginStart: spacing.sm }}>
          <Text style={[typography.bodyBold, { color: state === "CURRENT" ? colors.primary : colors.textPrimary }]} numberOfLines={1}>
            {customerName}
          </Text>
          {timeLabel || distanceLabel ? (
            <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>
              {[timeLabel, distanceLabel].filter(Boolean).join(" · ")}
            </Text>
          ) : null}
        </View>
      </View>
    </Card>
  );
}
