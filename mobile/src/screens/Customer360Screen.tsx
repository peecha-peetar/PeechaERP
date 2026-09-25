import React, { useCallback, useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { Customer360Response } from "../api/types";
import { Button, Card, ErrorState, SkeletonList } from "../components";
import { formatAmount } from "../format";
import { formatJalaliDate, formatJalaliDateTime } from "../jalali";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  detailAccountId: number;
  onBack: () => void;
}

const GUARANTEE_TYPE_LABELS: Record<string, string> = {
  CHECK: "چکِ تضمینی", PROMISSORY_NOTE: "سفته", BANK_GUARANTEE: "ضمانت‌نامه", GUARANTOR: "ضامن", COLLATERAL: "وثیقه",
};
const ACTIVITY_TYPE_LABELS: Record<string, string> = {
  COMPLAINT: "شکایت", MEETING: "جلسه", OPPORTUNITY: "فرصتِ فروش", TASK: "وظیفه",
};
const CONTRACT_CATEGORY_LABELS: Record<string, string> = {
  STANDARD: "استاندارد", AGENCY: "نمایندگی", ORGANIZATIONAL: "سازمانی",
};
const ADDRESS_TYPE_LABELS: Record<string, string> = {
  OFFICE: "دفتر", STORE: "فروشگاه", WAREHOUSE: "انبار", DELIVERY: "تحویل", BILLING: "صورتحساب", RETURN: "مرجوعی",
};
const SEGMENT_LABELS: Record<string, string> = {
  NEW: "مشتریِ جدید", ACTIVE: "فعال", LOYAL: "وفادار", LOW_PURCHASE: "کم‌خرید",
  AT_RISK: "در معرضِ ریزش", INACTIVE: "غیرفعال", DEBTOR: "بدهکار", VIP: "VIP",
};

function SectionTitle({ label }: { label: string }) {
  const { colors, spacing, typography } = useTheme();
  return <Text style={[typography.captionBold, { color: colors.textSecondary, marginTop: spacing.md, marginBottom: spacing.sm }]}>{label}</Text>;
}

/** طبقِ بازبینیِ ساختارِ «تعریفِ مشتری» (R219، بخشِ ۱۲ -- Customer 360):
 * یک صفحه‌یِ واحد -- مالی/اعتبار، ضمانت‌ها، قراردادها، CRM (فعالیت/
 * تماس/یادداشت)، آدرس‌ها، Merchandising، ویزیت‌هایِ اخیر -- تا کاربر
 * مجبورِ جابه‌جایی بینِ چند صفحه نباشد. فقط نمایشی (خواندنی) است؛ ثبت/
 * ویرایشِ هرکدام از صفحه‌هایِ اختصاصیِ خودشان انجام می‌شود. */
export function Customer360Screen({ apiClient, detailAccountId, onBack }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [data, setData] = useState<Customer360Response | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await apiClient.getCustomer360(detailAccountId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافتِ اطلاعاتِ کاملِ مشتری ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [apiClient, detailAccountId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg }}>
        <SkeletonList count={5} />
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

  const { detail, guarantees, contracts, activities, addresses, merchandising, calls, notes, recent_visits: recentVisits, segment } = data;

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.sm, backgroundColor: colors.background }}>
      <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
      <Text style={[typography.h2, { color: colors.textPrimary }]}>{detail.name}</Text>
      <Text style={[typography.caption, { color: colors.textSecondary }]}>
        {detail.code} · {SEGMENT_LABELS[segment.segment_code] ?? segment.segment_code}
      </Text>

      <Card>
        <Text style={[typography.caption, { color: colors.textSecondary }]}>
          فروشِ ماهِ جاری: {formatAmount(segment.sales_this_month)} · فروشِ ۳ماهِ اخیر: {formatAmount(segment.sales_last_3_months)}
        </Text>
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
          تعدادِ سفارش (۱۲ماهِ اخیر): {segment.order_count_last_12_months} · میانگینِ سفارش: {formatAmount(segment.avg_order_value)}
        </Text>
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
          سودِ برآوردیِ ۳ماهِ اخیر: {formatAmount(segment.estimated_profit_last_3_months)} (تخمینی، بر مبنایِ آخرین بهایِ تمام‌شده)
        </Text>
      </Card>

      <Card>
        <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>مانده‌یِ حساب</Text>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>{detail.balance_nature}</Text>
        </View>
        <Text style={[typography.numeric, { fontSize: 20, color: detail.balance_nature === "بدهکار" ? colors.danger : colors.success }]}>
          {formatAmount(detail.balance_amount)}
        </Text>
        {detail.credit_limit_amount ? (
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
            سقفِ اعتبار: {formatAmount(detail.credit_limit_amount)}
          </Text>
        ) : null}
      </Card>

      <SectionTitle label={`ضمانت‌ها (${guarantees.length})`} />
      {guarantees.length === 0 ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>ضمانتی ثبت نشده.</Text>
      ) : (
        guarantees.map((g) => (
          <Card key={g.guarantee_id}>
            <Text style={[typography.body, { color: colors.textPrimary }]}>
              {GUARANTEE_TYPE_LABELS[g.guarantee_type_code] ?? g.guarantee_type_code} · {formatAmount(g.amount)}
            </Text>
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              {g.status_code === "ACTIVE" ? "فعال" : g.status_code} {g.description ? `· ${g.description}` : ""}
            </Text>
          </Card>
        ))
      )}

      <SectionTitle label={`قراردادها (${contracts.length})`} />
      {contracts.length === 0 ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>قراردادی ثبت نشده.</Text>
      ) : (
        contracts.map((c) => (
          <Card key={c.contract_id}>
            <Text style={[typography.body, { color: colors.textPrimary }]}>
              {CONTRACT_CATEGORY_LABELS[c.contract_category_code] ?? c.contract_category_code} · {c.status_code}
            </Text>
            {c.committed_amount ? (
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                سهمیه: {formatAmount(c.committed_amount)} · مصرف‌شده: {formatAmount(c.consumed_amount)}
              </Text>
            ) : null}
            {c.commitments_text ? <Text style={[typography.caption, { color: colors.textSecondary }]}>{c.commitments_text}</Text> : null}
          </Card>
        ))
      )}

      <SectionTitle label={`فعالیت‌هایِ CRM (${activities.length})`} />
      {activities.length === 0 ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>فعالیتی ثبت نشده.</Text>
      ) : (
        activities.map((a) => (
          <Card key={a.activity_id}>
            <Text style={[typography.body, { color: colors.textPrimary }]}>
              {ACTIVITY_TYPE_LABELS[a.activity_type_code] ?? a.activity_type_code}: {a.subject}
            </Text>
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              {a.status_code} · {formatJalaliDate(a.created_at)}
            </Text>
          </Card>
        ))
      )}

      <SectionTitle label={`آدرس‌ها (${addresses.length})`} />
      {addresses.length === 0 ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>آدرسی ثبت نشده.</Text>
      ) : (
        addresses.map((ad) => (
          <Card key={ad.address_id}>
            <Text style={[typography.body, { color: colors.textPrimary }]}>
              {ADDRESS_TYPE_LABELS[ad.address_type_code] ?? ad.address_type_code}
            </Text>
            <Text style={[typography.caption, { color: colors.textSecondary }]}>{ad.line1}</Text>
          </Card>
        ))
      )}

      {merchandising ? (
        <>
          <SectionTitle label="اطلاعاتِ فروشگاهی" />
          <Card>
            {merchandising.store_area_sqm ? (
              <Text style={[typography.caption, { color: colors.textSecondary }]}>متراژ: {merchandising.store_area_sqm} مترمربع</Text>
            ) : null}
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              {[
                merchandising.checkout_count !== null ? `صندوق: ${merchandising.checkout_count}` : null,
                merchandising.fridge_count !== null ? `یخچال: ${merchandising.fridge_count}` : null,
                merchandising.shelf_count !== null ? `قفسه: ${merchandising.shelf_count}` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </Text>
            {merchandising.available_brands ? (
              <Text style={[typography.caption, { color: colors.textSecondary }]}>برندهایِ موجود: {merchandising.available_brands}</Text>
            ) : null}
            {merchandising.competitor_brands ? (
              <Text style={[typography.caption, { color: colors.textSecondary }]}>رقبا: {merchandising.competitor_brands}</Text>
            ) : null}
          </Card>
        </>
      ) : null}

      <SectionTitle label={`ویزیت‌هایِ اخیر (${recentVisits.length})`} />
      {recentVisits.length === 0 ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>ویزیتی ثبت نشده.</Text>
      ) : (
        recentVisits.map((v) => (
          <Card key={v.customer_visit_id}>
            <Text style={[typography.body, { color: colors.textPrimary }]}>{formatJalaliDateTime(v.checked_in_at)}</Text>
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              {v.status_code}
              {v.is_outside_geofence ? " · خارج از محدوده" : ""}
            </Text>
          </Card>
        ))
      )}

      {calls.length > 0 ? (
        <>
          <SectionTitle label={`تماس‌ها (${calls.length})`} />
          {calls.map((c) => (
            <Card key={c.call_log_id}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>{c.phone_number}</Text>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                {formatJalaliDateTime(c.started_at)} · {c.was_successful ? "موفق" : "ناموفق"}
              </Text>
            </Card>
          ))}
        </>
      ) : null}

      {notes.length > 0 ? (
        <>
          <SectionTitle label={`یادداشت‌ها (${notes.length})`} />
          {notes.map((n) => (
            <Card key={n.note_id}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>{n.note_text}</Text>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>{formatJalaliDate(n.created_at)}</Text>
            </Card>
          ))}
        </>
      ) : null}
    </ScrollView>
  );
}
