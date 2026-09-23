import React, { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { DebtorRow, TodayCollectionRow } from "../api/types";
import { CustomerCard, EmptyState, ErrorState, PaymentItem, SkeletonList } from "../components";
import { formatAmount } from "../format";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  onOpenCustomer: (detailAccountId: number) => void;
}

/** طبقِ Phase 5 (تکمیل): «لیستِ بدهکاران» + «وصولِ امروز» برایِ خودِ
 * ویزیتور/مأمورِ وصول -- بدهکاران فقط مشتریانِ همین کاربر (برنامه‌یِ
 * ویزیت) را نشان می‌دهد. زدنِ هر بدهکار به جزئیاتِ مشتری می‌رود که
 * دکمه‌یِ «ثبتِ وصول» همان‌جاست -- بدونِ تکرارِ فرمِ وصول در این صفحه.
 *
 * محدودیتِ شناخته‌شده: تفکیکِ «عقب‌افتاده» از «هنوز در مهلت» نیست
 * (نیازمندِ Agingِ واقعی بر اساسِ سررسیدِ هر فاکتور -- کارِ جداگانه). */
export function CollectionListScreen({ apiClient, onOpenCustomer }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [debtors, setDebtors] = useState<DebtorRow[]>([]);
  const [todayCollections, setTodayCollections] = useState<TodayCollectionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [debtorRows, todayRows] = await Promise.all([apiClient.listDebtors(), apiClient.listTodayCollections()]);
      setDebtors(debtorRows);
      setTodayCollections(todayRows);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافتِ اطلاعاتِ وصول ناموفق بود.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiClient]);

  useEffect(() => {
    load();
  }, [load]);

  const totalCollectedToday = todayCollections.reduce((sum, r) => sum + Number(r.amount), 0);

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg }}>
        <SkeletonList count={4} />
      </View>
    );
  }

  if (error) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <ErrorState description={error} onRetry={load} />
      </View>
    );
  }

  return (
    <ScrollView
      contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg, backgroundColor: colors.background }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
    >
      <Text style={[typography.h2, { color: colors.textPrimary }]}>وصول</Text>

      <View>
        <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.sm }]}>
          وصولِ امروز {totalCollectedToday > 0 ? `· ${formatAmount(String(totalCollectedToday))}` : ""}
        </Text>
        {todayCollections.length === 0 ? (
          <EmptyState icon="💰" title="هنوز وصولی ثبت نشده" />
        ) : (
          <View>
            {todayCollections.map((row) => (
              <PaymentItem
                key={row.journal_entry_id}
                method="CASH"
                amountLabel={formatAmount(row.amount)}
                customerName={row.customer_name ?? "نامشخص"}
                dateLabel="امروز"
              />
            ))}
          </View>
        )}
      </View>

      <View>
        <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.sm }]}>بدهکاران</Text>
        {debtors.length === 0 ? (
          <EmptyState icon="✅" title="بدهکاری در برنامه‌یِ شما نیست" />
        ) : (
          <View style={{ gap: spacing.sm }}>
            {debtors.map((d) => (
              <CustomerCard
                key={d.detail_account_id}
                code={d.code}
                name={d.name}
                balanceLabel={formatAmount(d.balance_amount)}
                isOverdue
                onPress={() => onOpenCustomer(d.detail_account_id)}
              />
            ))}
          </View>
        )}
      </View>
    </ScrollView>
  );
}
