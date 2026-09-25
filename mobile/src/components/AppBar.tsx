import React from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

export type SyncStatus = "IDLE" | "SYNCING" | "SYNCED" | "OFFLINE" | "ERROR";

const SYNC_LABEL: Record<SyncStatus, string> = {
  IDLE: "آماده",
  SYNCING: "درحالِ Sync",
  SYNCED: "به‌روز",
  OFFLINE: "آفلاین",
  ERROR: "خطایِ Sync",
};

interface AppBarProps {
  userFullName: string;
  syncStatus: SyncStatus;
  unreadNotificationCount?: number;
  onPressNotifications?: () => void;
  onPressProfile?: () => void;
}

/** طبقِ ساختارِ پیشنهادیِ کاربر: بالایِ صفحه = نامِ کاربر + وضعیتِ Sync +
 * اعلان‌ها + منویِ پروفایل -- در همه‌یِ صفحاتِ اصلی یکسان (نه هر صفحه
 * AppBarِ خودش را دوباره بسازد). */
export function AppBar({ userFullName, syncStatus, unreadNotificationCount = 0, onPressNotifications, onPressProfile }: AppBarProps) {
  const { colors, spacing, typography } = useTheme();
  const syncTone = syncStatus === "ERROR" ? colors.danger : syncStatus === "OFFLINE" ? colors.warning : colors.success;

  return (
    <View style={[styles.container, { backgroundColor: colors.surface, borderBottomColor: colors.border, paddingHorizontal: spacing.lg }]}>
      <TouchableOpacity onPress={onPressProfile} style={styles.left} accessibilityRole="button">
        <View style={[styles.avatar, { backgroundColor: colors.primarySoft }]}>
          <Text style={[typography.bodyBold, { color: colors.primary, textAlign: "center" }]}>{userFullName.trim().charAt(0) || "؟"}</Text>
        </View>
        <View style={{ marginStart: spacing.sm }}>
          <Text style={[typography.bodyBold, { color: colors.textPrimary }]} numberOfLines={1}>
            {userFullName}
          </Text>
          <View style={styles.syncRow}>
            <View style={[styles.syncDot, { backgroundColor: syncTone }]} />
            <Text style={[typography.caption, { color: syncTone, marginStart: spacing.xxs }]}>{SYNC_LABEL[syncStatus]}</Text>
          </View>
        </View>
      </TouchableOpacity>

      <TouchableOpacity onPress={onPressNotifications} accessibilityRole="button" style={styles.bell}>
        <Text style={[typography.captionBold, { color: colors.textPrimary }]}>اعلان‌ها</Text>
        {unreadNotificationCount > 0 ? (
          <View style={[styles.badge, { backgroundColor: colors.danger }]}>
            <Text style={[typography.captionBold, { color: colors.textInverse, fontSize: 10, textAlign: "center" }]}>
              {unreadNotificationCount > 9 ? "9+" : unreadNotificationCount}
            </Text>
          </View>
        ) : null}
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    height: 64,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  left: { flexDirection: "row", alignItems: "center", flexShrink: 1 },
  avatar: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  syncRow: { flexDirection: "row", alignItems: "center", marginTop: 2 },
  syncDot: { width: 7, height: 7, borderRadius: 4 },
  bell: { padding: 6 },
  badge: {
    position: "absolute",
    top: 0,
    end: 0,
    minWidth: 16,
    height: 16,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 2,
  },
});
