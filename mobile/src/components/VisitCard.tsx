import React from "react";
import { Text, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";
import { Card } from "./Card";

export type VisitCardState = "DONE" | "CURRENT" | "UPCOMING" | "SKIPPED";

const STATE_ICON: Record<VisitCardState, string> = { DONE: "✓", CURRENT: "→", UPCOMING: "○", SKIPPED: "✕" };

export interface VisitCardProps {
  customerName: string;
  timeLabel?: string;
  distanceLabel?: string;
  state: VisitCardState;
  onPress?: () => void;
}

/** طبقِ صفحه‌یِ خانه‌یِ پیشنهادیِ کاربر («✓ فروشگاه احمدی / → فروشگاه
 * محمدی / ○ سوپرمارکت رضایی») -- لیستِ برنامه‌یِ امروز دقیقاً با همین
 * نمادها. */
export function VisitCard({ customerName, timeLabel, distanceLabel, state, onPress }: VisitCardProps) {
  const { colors, spacing, typography } = useTheme();
  const stateColor = { DONE: colors.success, CURRENT: colors.primary, UPCOMING: colors.textSecondary, SKIPPED: colors.danger }[state];

  return (
    <Card onPress={onPress} style={{ paddingVertical: spacing.md }}>
      <View style={{ flexDirection: "row", alignItems: "center" }}>
        <Text style={{ color: stateColor, fontSize: 18, fontWeight: "700", width: 24, textAlign: "center" }}>
          {STATE_ICON[state]}
        </Text>
        <View style={{ flex: 1, marginStart: spacing.sm }}>
          <Text style={[typography.bodyBold, { color: state === "CURRENT" ? colors.primary : colors.textPrimary }]} numberOfLines={1}>
            {customerName}
          </Text>
          {timeLabel || distanceLabel ? (
            <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>
              {[timeLabel, distanceLabel ? `📍 ${distanceLabel}` : null].filter(Boolean).join(" · ")}
            </Text>
          ) : null}
        </View>
      </View>
    </Card>
  );
}
