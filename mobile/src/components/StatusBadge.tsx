import React from "react";
import { Text, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";
import { statusTone, toneColor } from "../theme/statusColors";

interface StatusBadgeProps {
  statusCode: string;
  label: string;
}

export function StatusBadge({ statusCode, label }: StatusBadgeProps) {
  const { colors, spacing, radius, typography } = useTheme();
  const { bg, fg } = toneColor(statusTone(statusCode), colors);
  return (
    <View
      style={{
        backgroundColor: bg,
        borderRadius: radius.pill,
        paddingHorizontal: spacing.sm,
        paddingVertical: spacing.xxs,
        alignSelf: "flex-start",
      }}
    >
      <Text style={[typography.captionBold, { color: fg }]}>{label}</Text>
    </View>
  );
}
