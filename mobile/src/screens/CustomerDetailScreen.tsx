import React, { useCallback, useEffect, useState } from "react";
import { Linking, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { CustomerDetailResponse, CustomerRow, VisitPlanRow } from "../api/types";
import { formatAmount } from "../format";
import { Button, Card, ErrorState, SkeletonList, StatusBadge } from "../components";
import { formatJalaliDate } from "../jalali";
import { LocalCache } from "../storage/localCache";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  localCache: LocalCache;
  detailAccountId: number;
  onBack: () => void;
  onStartVisit: (customer: CustomerRow, visitPlan: VisitPlanRow) => void;
  onCreateOrder: (customer: CustomerRow) => void;
  onCreateCollection: (customer: CustomerRow) => void;
  /** طبقِ درخواستِ صریحِ کاربر («وصولگر فقط به دنبالِ وصول باشه»):
   * دکمه‌هایِ «شروعِ ویزیت»/«ثبتِ سفارش» را پنهان می‌کند -- فقط برایِ
   * حالتِ خالصِ وصول. */
  collectionOnly?: boolean;
}

const STATUS_LABELS: Record<string, string> = {
  ACTIVE: "فعال",
  PENDING_APPROVAL: "درانتظارِ تایید",
  SUSPENDED: "معلق",
  BLACKLISTED: "لیستِ سیاه",
  INACTIVE: "غیرِفعال",
};

/** طبقِ اصلِ صریح (نیازمندی‌هایِ صفحه‌یِ مشتری): مانده/سقفِ اعتبار/
 * آخرین‌خرید/پرفروش‌ترین‌کالاها/تاریخچه از یک درخواستِ تکی
 * (GET /customers/{id})، به‌اضافه‌یِ اقدام‌هایِ سریع (شروعِ ویزیت/ثبتِ
 * سفارش/ثبتِ وصول/تماس/مسیریابی). */
export function CustomerDetailScreen({
  apiClient,
  localCache,
  detailAccountId,
  onBack,
  onStartVisit,
  onCreateOrder,
  onCreateCollection,
  collectionOnly,
}: Props) {
  const { colors, spacing, typography } = useTheme();
  const [detail, setDetail] = useState<CustomerDetailResponse | null>(null);
  const [visitPlan, setVisitPlan] = useState<VisitPlanRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [data, cached] = await Promise.all([apiClient.getCustomerDetail(detailAccountId), localCache.getPullResponse()]);
      setDetail(data);
      setVisitPlan(cached?.visit_plans.find((p) => p.customer_detail_account_id === detailAccountId) ?? null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافتِ اطلاعاتِ مشتری ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [apiClient, localCache, detailAccountId]);

  useEffect(() => {
    load();
  }, [load]);

  const toCustomerRow = (): CustomerRow | null =>
    detail === null
      ? null
      : {
          detail_account_id: detail.detail_account_id,
          code: detail.code,
          name: detail.name,
          gps_latitude: detail.gps_latitude ? Number(detail.gps_latitude) : null,
          gps_longitude: detail.gps_longitude ? Number(detail.gps_longitude) : null,
        };

  const callCustomer = () => {
    if (detail?.phone) Linking.openURL(`tel:${detail.phone}`);
  };

  const navigateToCustomer = () => {
    if (detail?.gps_latitude && detail?.gps_longitude) {
      Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${detail.gps_latitude},${detail.gps_longitude}`);
    } else if (detail?.address) {
      Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(detail.address)}`);
    }
  };

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg }}>
        <SkeletonList count={4} />
      </View>
    );
  }

  if (error || detail === null) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <ErrorState description={error ?? "مشتری یافت نشد."} onRetry={load} />
      </View>
    );
  }

  const customerRow = toCustomerRow()!;

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.lg, backgroundColor: colors.background }}>
      <Button label="← بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />

      <View>
        <Text style={[typography.h2, { color: colors.textPrimary }]}>{detail.name}</Text>
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>{detail.code}</Text>
        {detail.status_code ? (
          <View style={{ marginTop: spacing.sm }}>
            <StatusBadge statusCode={detail.status_code} label={STATUS_LABELS[detail.status_code] ?? detail.status_code} />
          </View>
        ) : null}
      </View>

      <Card>
        <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>مانده‌یِ حساب</Text>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>{detail.balance_nature}</Text>
        </View>
        <Text
          style={[
            typography.numeric,
            { fontSize: 22, color: detail.balance_nature === "بدهکار" ? colors.danger : colors.success, marginTop: spacing.xs },
          ]}
        >
          {formatAmount(detail.balance_amount)}
        </Text>
        {detail.credit_limit_amount ? (
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.sm }]}>
            سقفِ اعتبار: {formatAmount(detail.credit_limit_amount)} · مهلتِ پرداخت: {detail.payment_term_days} روز
          </Text>
        ) : null}
        {detail.last_purchase_date ? (
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
            آخرین خرید: {formatJalaliDate(detail.last_purchase_date)}
          </Text>
        ) : null}
      </Card>

      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
        {!collectionOnly ? (
          <Button
            label="📍 شروعِ ویزیت"
            fullWidth={false}
            disabled={visitPlan === null}
            onPress={() => visitPlan && onStartVisit(customerRow, visitPlan)}
          />
        ) : null}
        {!collectionOnly ? (
          <Button label="🛒 ثبتِ سفارش" fullWidth={false} variant="secondary" onPress={() => onCreateOrder(customerRow)} />
        ) : null}
        <Button label="💰 ثبتِ وصول" fullWidth={false} variant="secondary" onPress={() => onCreateCollection(customerRow)} />
        {detail.phone ? <Button label="📞 تماس" fullWidth={false} variant="ghost" onPress={callCustomer} /> : null}
        {detail.gps_latitude || detail.address ? (
          <Button label="🗺️ مسیریابی" fullWidth={false} variant="ghost" onPress={navigateToCustomer} />
        ) : null}
      </View>
      {!collectionOnly && visitPlan === null ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>این مشتری برنامه‌یِ ویزیتِ ثبت‌شده‌ای ندارد.</Text>
      ) : null}

      {detail.top_products.length > 0 ? (
        <View>
          <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.sm }]}>محصولاتِ پرفروش</Text>
          <Card>
            {detail.top_products.map((p, index) => (
              <View
                key={p.item_id}
                style={{
                  flexDirection: "row",
                  justifyContent: "space-between",
                  paddingVertical: spacing.xs,
                  borderTopWidth: index === 0 ? 0 : 1,
                  borderTopColor: colors.border,
                }}
              >
                <Text style={[typography.body, { color: colors.textPrimary }]}>{p.item_name ?? `کالایِ #${p.item_id}`}</Text>
                <Text style={[typography.numeric, { color: colors.textSecondary }]}>{p.total_quantity}</Text>
              </View>
            ))}
          </Card>
        </View>
      ) : null}

      {detail.recent_documents.length > 0 ? (
        <View>
          <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.sm }]}>سفارش‌ها/فاکتورهایِ اخیر</Text>
          <Card>
            {detail.recent_documents.map((d, index) => (
              <View
                key={d.document_id}
                style={{
                  flexDirection: "row",
                  justifyContent: "space-between",
                  paddingVertical: spacing.xs,
                  borderTopWidth: index === 0 ? 0 : 1,
                  borderTopColor: colors.border,
                }}
              >
                <Text style={[typography.body, { color: colors.textPrimary }]}>
                  #{d.document_no} · {formatJalaliDate(d.document_date)}
                </Text>
                <Text style={[typography.numeric, { color: colors.textPrimary }]}>{formatAmount(d.total_amount)}</Text>
              </View>
            ))}
          </Card>
        </View>
      ) : null}
    </ScrollView>
  );
}
