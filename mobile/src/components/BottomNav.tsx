import React from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

export type BottomNavKey = "HOME" | "VISITS" | "CUSTOMERS" | "ORDER" | "COLLECTION";

interface BottomNavItem {
  key: BottomNavKey;
  label: string;
  icon: string;
}

const ITEMS: BottomNavItem[] = [
  { key: "HOME", label: "خانه", icon: "🏠" },
  { key: "VISITS", label: "ویزیت‌ها", icon: "📍" },
  { key: "CUSTOMERS", label: "مشتریان", icon: "👥" },
  { key: "ORDER", label: "سفارش", icon: "🛒" },
  { key: "COLLECTION", label: "وصول", icon: "💰" },
];

interface BottomNavProps {
  active: BottomNavKey;
  onChange: (key: BottomNavKey) => void;
  badgeCounts?: Partial<Record<BottomNavKey, number>>;
  /** طبقِ درخواستِ صریحِ کاربر («وصولگر فقط به دنبالِ وصول باشه»): اگر
   * داده نشود، هر ۵ تب نشان داده می‌شود (رفتارِ قبلی) -- برایِ حالتِ
   * «وصول»، فقط زیرمجموعه‌ای از تب‌ها مربوط است. */
  visibleKeys?: BottomNavKey[];
}

/** طبقِ ساختارِ پیشنهادیِ کاربر: ۵ تبِ ثابت، بدونِ react-navigation
 * (محدودیتِ سندباکس -- توضیح در App.tsx) -- این کامپوننت فقط UI است،
 * تغییرِ صفحه با همان روتینگِ دستیِ App.tsx انجام می‌شود. */
export function BottomNav({ active, onChange, badgeCounts, visibleKeys }: BottomNavProps) {
  const { colors, spacing, typography } = useTheme();
  const visibleItems = visibleKeys ? ITEMS.filter((item) => visibleKeys.includes(item.key)) : ITEMS;
  return (
    <View style={[styles.container, { backgroundColor: colors.surface, borderTopColor: colors.border }]}>
      {visibleItems.map((item) => {
        const isActive = item.key === active;
        const badge = badgeCounts?.[item.key];
        return (
          <TouchableOpacity
            key={item.key}
            accessibilityRole="tab"
            accessibilityState={{ selected: isActive }}
            style={styles.item}
            onPress={() => onChange(item.key)}
          >
            <View>
              <Text style={{ fontSize: 20 }}>{item.icon}</Text>
              {badge ? (
                <View style={[styles.badge, { backgroundColor: colors.danger }]}>
                  <Text style={{ color: colors.textInverse, fontSize: 10, fontWeight: "700" }}>
                    {badge > 9 ? "9+" : badge}
                  </Text>
                </View>
              ) : null}
            </View>
            <Text
              style={[
                typography.caption,
                { color: isActive ? colors.primary : colors.textSecondary, marginTop: spacing.xxs },
              ]}
            >
              {item.label}
            </Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingBottom: 6,
    paddingTop: 8,
  },
  item: { flex: 1, alignItems: "center", justifyContent: "center" },
  badge: {
    position: "absolute",
    top: -4,
    end: -8,
    minWidth: 16,
    height: 16,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 2,
  },
});
