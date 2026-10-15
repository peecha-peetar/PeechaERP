import React from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

export type BottomNavKey = "HOME" | "VISITS" | "CUSTOMERS" | "ORDER" | "COLLECTION" | "REPORTS";

interface BottomNavItem {
  key: BottomNavKey;
  label: string;
}

// طبقِ درخواستِ صریحِ کاربر («از ایکن‌ها استفاده نکن»): برچسبِ متنی
// به‌تنهایی -- بدونِ ایموجی/گلیفِ تزئینی -- برایِ هر تب.
const ITEMS: BottomNavItem[] = [
  { key: "HOME", label: "خانه" },
  { key: "VISITS", label: "ویزیت‌ها" },
  { key: "CUSTOMERS", label: "مشتریان" },
  { key: "ORDER", label: "سفارش" },
  { key: "REPORTS", label: "گزارشات" },
  { key: "COLLECTION", label: "وصول" },
];

interface BottomNavProps {
  active: BottomNavKey;
  onChange: (key: BottomNavKey) => void;
  badgeCounts?: Partial<Record<BottomNavKey, number>>;
  /** طبقِ درخواستِ صریحِ کاربر («وصولگر فقط به دنبالِ وصول باشه»): اگر
   * داده نشود، همه‌یِ تب‌ها نشان داده می‌شود -- برایِ حالت‌هایی که
   * فقط زیرمجموعه‌ای از تب‌ها مربوط است (وصول/پخشِ گرم/پخشِ سرد). */
  visibleKeys?: BottomNavKey[];
  /** طبقِ درخواستِ صریحِ کاربر («در پخشِ گرم فاکتور، در پخشِ سرد
   * سفارش»): همان تبِ ORDER بسته به حالت برچسبِ متفاوتی می‌خواهد --
   * به‌جایِ ساختنِ یک تبِ تازه برایِ همان صفحه. */
  labelOverrides?: Partial<Record<BottomNavKey, string>>;
}

/** طبقِ ساختارِ پیشنهادیِ کاربر: تب‌هایِ ثابت، بدونِ react-navigation
 * (محدودیتِ سندباکس -- توضیح در App.tsx) -- این کامپوننت فقط UI است،
 * تغییرِ صفحه با همان روتینگِ دستیِ App.tsx انجام می‌شود. */
export function BottomNav({ active, onChange, badgeCounts, visibleKeys, labelOverrides }: BottomNavProps) {
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
              {badge ? (
                <View style={[styles.badge, { backgroundColor: colors.danger }]}>
                  <Text style={[typography.captionBold, { color: colors.textInverse, fontSize: 10, textAlign: "center" }]}>
                    {badge > 9 ? "9+" : badge}
                  </Text>
                </View>
              ) : null}
              <Text
                style={[
                  typography.captionBold,
                  { color: isActive ? colors.primary : colors.textSecondary },
                ]}
              >
                {labelOverrides?.[item.key] ?? item.label}
              </Text>
            </View>
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
    paddingTop: 10,
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
