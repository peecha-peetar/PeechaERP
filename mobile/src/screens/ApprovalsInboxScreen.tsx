import React, { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { ApprovalsResponse } from "../api/types";
import { Button, Card, EmptyState, ErrorState, SkeletonList, useToast } from "../components";
import { formatJalaliDateTime } from "../jalali";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  onBack: () => void;
  onOpenCustomer: (detailAccountId: number) => void;
}

/** طبقِ گزارشِ آدیت («بک‌اند یک endpointِ کاملِ /approvals دارد که
 * کاملاً یتیم است -- هیچ صفحه/متدِ موبایلی صدایش نمی‌زند؛ مدیر باید هر
 * مشتری را تک‌تک باز کند»): این صفحه دو منبعِ تاییدِ ازپیش‌موجود را در
 * یک‌جا جمع می‌کند -- کارتابلِ عمومیِ اسناد (تاییدِ مستقیم این‌جا) و
 * مشتریانِ درانتظار (زدنِ هرکدام به CustomerDetailScreenِ همان مشتری
 * می‌رود، جایی که دکمه‌هایِ تایید/ردِ واقعی از پیش وجود دارند -- بدونِ
 * تکرارِ آن منطق این‌جا). */
export function ApprovalsInboxScreen({ apiClient, onBack, onOpenCustomer }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [data, setData] = useState<ApprovalsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decidingId, setDecidingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await apiClient.listApprovals());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافتِ صندوقِ تاییدها ناموفق بود.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiClient]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (cartableItemId: number, approve: boolean) => {
    setDecidingId(cartableItemId);
    try {
      if (approve) {
        await apiClient.approveCartableItem(cartableItemId);
      } else {
        await apiClient.rejectCartableItem(cartableItemId);
      }
      toast.show(approve ? "تایید شد." : "رد شد.", "success");
      await load();
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "ثبتِ تصمیم ناموفق بود.", "danger");
    } finally {
      setDecidingId(null);
    }
  };

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg }}>
        <SkeletonList count={4} />
      </View>
    );
  }

  if (error || data === null) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <ErrorState description={error ?? "اطلاعات یافت نشد."} onRetry={load} />
      </View>
    );
  }

  const { cartable_tasks: cartableTasks, pending_customers: pendingCustomers } = data;
  const isEmpty = cartableTasks.length === 0 && pendingCustomers.length === 0;

  return (
    <ScrollView
      contentContainerStyle={{ padding: spacing.lg, gap: spacing.md, backgroundColor: colors.background }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
    >
      <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
      <Text style={[typography.h2, { color: colors.textPrimary }]}>صندوقِ تاییدها</Text>

      {isEmpty ? (
        <EmptyState title="کاری در انتظارِ تاییدِ شما نیست" />
      ) : (
        <>
          {cartableTasks.length > 0 ? (
            <View>
              <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.sm }]}>
                کارتابل ({cartableTasks.length})
              </Text>
              <View style={{ gap: spacing.sm }}>
                {cartableTasks.map((t) => (
                  <Card key={t.cartable_item_id}>
                    <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>{t.form_label}</Text>
                    {t.description ? (
                      <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>{t.description}</Text>
                    ) : null}
                    <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
                      {t.submitted_by_name ?? "نامشخص"}
                      {t.submitted_at ? ` · ${formatJalaliDateTime(t.submitted_at)}` : ""}
                      {` · مرحله‌یِ ${t.current_step_no} از ${t.total_steps}`}
                    </Text>
                    <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
                      <Button
                        label="تایید"
                        size="md"
                        fullWidth={false}
                        loading={decidingId === t.cartable_item_id}
                        onPress={() => decide(t.cartable_item_id, true)}
                      />
                      <Button
                        label="رد"
                        size="md"
                        variant="danger"
                        fullWidth={false}
                        loading={decidingId === t.cartable_item_id}
                        onPress={() => decide(t.cartable_item_id, false)}
                      />
                    </View>
                  </Card>
                ))}
              </View>
            </View>
          ) : null}

          {pendingCustomers.length > 0 ? (
            <View>
              <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.sm }]}>
                مشتریانِ درانتظارِ تایید ({pendingCustomers.length})
              </Text>
              <View style={{ gap: spacing.sm }}>
                {pendingCustomers.map((c) => (
                  <Card key={c.customer_detail_account_id} onPress={() => onOpenCustomer(c.customer_detail_account_id)}>
                    <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>{c.name ?? `مشتریِ #${c.customer_detail_account_id}`}</Text>
                    <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
                      {c.code ?? ""}
                      {c.submitted_at ? ` · ${formatJalaliDateTime(c.submitted_at)}` : ""}
                    </Text>
                  </Card>
                ))}
              </View>
            </View>
          ) : null}
        </>
      )}
    </ScrollView>
  );
}
