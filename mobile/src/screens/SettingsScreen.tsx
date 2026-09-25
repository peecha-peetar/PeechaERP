import React, { useCallback, useEffect, useState } from "react";
import { Alert, ScrollView, Text, View } from "react-native";
import { ApiClient } from "../api/client";
import { Button, Card } from "../components";
import { formatJalaliDateTime } from "../jalali";
import { OfflineQueue } from "../sync/offlineQueue";
import { SyncEngine } from "../sync/syncEngine";
import { SyncErrorEntry, SyncErrorLog } from "../sync/syncErrorLog";
import { useTheme, useThemeControls } from "../theme";

interface Props {
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  syncEngine: SyncEngine;
  syncErrorLog: SyncErrorLog;
  userFullName: string;
  onLoggedOut: () => void;
  onBack: () => void;
  onOpenManagerDashboard: () => void;
  /** طبقِ درخواستِ صریحِ کاربر («تسویه آخر روز باید بصورتِ انتخابی به
   * یک نفر از ۳ نقش واگذار بشه»): فقط برایِ همان یک نفر تعریف می‌شود --
   * undefined یعنی این کاربر مسئولِ تسویهٔ هیچ خودرویی نیست. */
  onOpenVehicleSettlement?: () => void;
  /** طبقِ درخواستِ صریحِ کاربر («کاربر اول برنامه انتخاب کنه پخش گرم و
   * سرد»): چون این انتخاب فقط برایِ همان نشستِ اپ است (نه یک تنظیمِ
   * دائمی)، این‌جا راهی برایِ عوض‌کردنش می‌گذاریم -- برایِ روزی که
   * ویزیتور برنامه‌اش عوض شود، بدونِ نیاز به خروج/ورودِ دوباره. */
  onChangeMode: () => void;
}

/** طبقِ اصلِ صریح («Dark/Light Theme»): سوییچِ دستیِ تم + خروجِ حساب --
 * حداقلیِ لازم برایِ UI-7؛ تنظیماتِ بیشتر (مثلِ اعلان‌هایِ Push) در
 * فازهایِ بعدی که خودِ آن قابلیت‌ها ساخته شوند اضافه می‌شود.
 *
 * دکمه‌یِ داشبوردِ مدیریت همیشه نشان داده می‌شود (اپِ موبایل نمی‌داند
 * کاربرِ فعلی مدیر است یا نه -- سرور خودش با ۴۰۳ تصمیم می‌گیرد، همان
 * الگویِ RBACِ لایه‌یِ API؛ ManagerDashboardScreen آن خطا را با پیامِ
 * روشن نشان می‌دهد، نه Crash).
 *
 * دکمه‌یِ پاکسازیِ صفِ آفلاین (طبقِ باگِ واقعیِ کشف‌شده رویِ دستگاهِ
 * فیزیکی: یک عکسِ خیلی‌بزرگ در صف باعثِ شکستِ دائمیِ خواندنِ کلِ صف
 * می‌شود -- "Row too big to fit into CursorWindow") تنها راهِ بازیابیِ
 * کاربر از چنین حالتی است، بدونِ نیاز به پاک‌کردنِ کاملِ دیتایِ اپ. */
export function SettingsScreen({
  apiClient, offlineQueue, syncEngine, syncErrorLog, userFullName, onLoggedOut, onBack, onOpenManagerDashboard,
  onOpenVehicleSettlement, onChangeMode,
}: Props) {
  const { colors, spacing, typography, mode } = useTheme();
  const { toggleMode } = useThemeControls();
  const [pendingCount, setPendingCount] = useState(0);
  const [errors, setErrors] = useState<SyncErrorEntry[]>([]);
  const [syncing, setSyncing] = useState(false);

  const refreshSyncInfo = useCallback(async () => {
    setPendingCount(await offlineQueue.size());
    setErrors(await syncErrorLog.list());
  }, [offlineQueue, syncErrorLog]);

  useEffect(() => {
    refreshSyncInfo();
  }, [refreshSyncInfo]);

  const logout = async () => {
    await apiClient.logout();
    onLoggedOut();
  };

  const syncNow = async () => {
    setSyncing(true);
    try {
      await syncEngine.pull();
      const result = await syncEngine.pushQueue();
      if (result.failedButKept.length > 0) {
        await syncErrorLog.record(result.failedButKept);
      }
    } finally {
      setSyncing(false);
      await refreshSyncInfo();
    }
  };

  const clearErrorLog = async () => {
    await syncErrorLog.clear();
    await refreshSyncInfo();
  };

  const clearOfflineQueue = () => {
    Alert.alert(
      "پاکسازیِ صفِ آفلاین",
      "همه‌یِ عملیات‌هایِ درحالِ‌انتظارِ ارسال (که هنوز به سرور نرسیده‌اند) برایِ همیشه حذف می‌شوند. این کار را فقط وقتی بزن که صف قفل شده و ارسال نمی‌شود.",
      [
        { text: "انصراف", style: "cancel" },
        {
          text: "پاک‌کن",
          style: "destructive",
          onPress: async () => {
            await offlineQueue.clear();
            Alert.alert("انجام شد", "صفِ آفلاین پاک شد.");
            await refreshSyncInfo();
          },
        },
      ],
    );
  };

  return (
    <ScrollView contentContainerStyle={{ backgroundColor: colors.background, padding: spacing.lg, gap: spacing.lg }}>
      <Button label="← بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
      <Text style={[typography.h2, { color: colors.textPrimary }]}>تنظیمات</Text>

      <Card>
        <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>{userFullName}</Text>
      </Card>

      <Card>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <Text style={[typography.body, { color: colors.textPrimary }]}>پوسته‌یِ تیره</Text>
          <Button label={mode === "dark" ? "فعال ✓" : "غیرِفعال"} variant="secondary" fullWidth={false} onPress={toggleMode} />
        </View>
      </Card>

      <Card>
        <Text style={[typography.bodyBold, { color: colors.textPrimary, marginBottom: spacing.sm }]}>وضعیتِ همگام‌سازی</Text>
        <Text style={[typography.body, { color: colors.textSecondary }]}>
          {pendingCount === 0 ? "همه‌چیز همگام است." : `${pendingCount} عملیاتِ درحالِ‌انتظار`}
        </Text>
        <View style={{ marginTop: spacing.sm }}>
          <Button
            label={syncing ? "در حالِ همگام‌سازی..." : "🔄 همگام‌سازیِ دستی"}
            variant="secondary"
            onPress={syncNow}
            disabled={syncing}
          />
        </View>
      </Card>

      {errors.length > 0 ? (
        <Card>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm }}>
            <Text style={[typography.bodyBold, { color: colors.danger }]}>آخرین خطاهایِ همگام‌سازی</Text>
            <Button label="پاکسازی" variant="ghost" fullWidth={false} onPress={clearErrorLog} />
          </View>
          {errors.map((e, index) => (
            <View
              key={`${e.idempotencyKey}-${index}`}
              style={{ paddingVertical: spacing.xs, borderTopWidth: index === 0 ? 0 : 1, borderTopColor: colors.border }}
            >
              <Text style={[typography.caption, { color: colors.textSecondary }]}>{formatJalaliDateTime(e.occurredAt)}</Text>
              <Text style={[typography.body, { color: colors.textPrimary, marginTop: 2 }]}>{e.reason}</Text>
            </View>
          ))}
        </Card>
      ) : null}

      <Button label="🔁 تغییرِ حالتِ پخش (گرم/سرد)" variant="secondary" onPress={onChangeMode} />

      <Button label="📊 داشبوردِ مدیریت" variant="secondary" onPress={onOpenManagerDashboard} />

      {onOpenVehicleSettlement ? (
        <Button label="🚚 تسویهٔ پایانِ روزِ خودرو" variant="secondary" onPress={onOpenVehicleSettlement} />
      ) : null}

      <Button label="🧹 پاکسازیِ صفِ آفلاین (اضطراری)" variant="secondary" onPress={clearOfflineQueue} />

      <Button label="خروج از حساب" variant="danger" onPress={logout} />
    </ScrollView>
  );
}
