import React, { useEffect, useRef } from "react";
import { ActivityIndicator, Animated, StyleSheet, Text, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

interface SkeletonProps {
  width?: number | `${number}%`;
  height?: number;
  style?: object;
}

/** طبقِ اصلِ صریح («Loading/Empty/Error State وجود داشته باشد»): Skeleton
 * به‌جایِ اسپینرِ تمام‌صفحه برایِ لیست‌ها (حسِ سریع‌تر/مدرن‌تر) --
 * اسپینر فقط برایِ عملیاتِ کوتاهِ داخلِ دکمه (Button loading) کافی است. */
export function Skeleton({ width = "100%", height = 16, style }: SkeletonProps) {
  const { colors, radius } = useTheme();
  const opacity = useRef(new Animated.Value(0.4)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 1, duration: 600, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.4, duration: 600, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [opacity]);

  return (
    <Animated.View
      style={[{ width, height, backgroundColor: colors.skeleton, borderRadius: radius.sm, opacity }, style]}
    />
  );
}

interface SkeletonCardProps {
  lines?: number;
}

export function SkeletonCard({ lines = 3 }: SkeletonCardProps) {
  const { colors, spacing, radius } = useTheme();
  return (
    <View style={[styles.card, { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg }]}>
      <Skeleton width="60%" height={18} style={{ marginBottom: spacing.md }} />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} height={12} style={{ marginBottom: spacing.sm }} />
      ))}
    </View>
  );
}

interface SkeletonListProps {
  count?: number;
}

export function SkeletonList({ count = 4 }: SkeletonListProps) {
  const { spacing } = useTheme();
  return (
    <View style={{ gap: spacing.md }}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </View>
  );
}

interface InlineSpinnerProps {
  label?: string;
}

export function InlineSpinner({ label }: InlineSpinnerProps) {
  const { colors, spacing, typography } = useTheme();
  return (
    <View style={{ alignItems: "center", paddingVertical: spacing.xl }}>
      <ActivityIndicator color={colors.primary} />
      {label ? <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.sm }]}>{label}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 0 },
});
