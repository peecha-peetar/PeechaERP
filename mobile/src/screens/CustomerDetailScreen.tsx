import React, { useCallback, useEffect, useState } from "react";
import { Linking, ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { CustomerDetailResponse, CustomerRow, SalesMode, VisitPlanRow } from "../api/types";
import { formatAmount } from "../format";
import { Button, Card, ErrorState, Input, SkeletonList, StatusBadge, useToast } from "../components";
import { printInvoice, shareInvoicePdf } from "../print/printInvoice";
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
  /** طبقِ درخواستِ صریحِ کاربر («در پخشِ گرم ویزیت معنی نداره»): دکمهٔ
   * «شروعِ ویزیت» پنهان و «ثبتِ سفارش» به «صدورِ فاکتور» تبدیل می‌شود. */
  vanSales?: boolean;
  /** طبقِ «پخشِ سرد و گرم کاملاً مجزا باشند»: سوابقِ اخیر فقط سندِ همین حالت. */
  salesMode?: SalesMode;
  /** طبقِ درخواستِ صریحِ کاربر («تاییدِ مشتری، داشبوردِ سرپرست»): دکمه‌هایِ
   * تایید/ردِ مشتریِ درانتظار فقط برایِ سرپرست نمایش داده می‌شوند. */
  isManager?: boolean;
  /** طبقِ چندآدرسیِ واقعی + GeoFence (R216، بخشِ ۲). */
  onOpenAddresses: () => void;
  /** طبقِ بازبینیِ ساختارِ «تعریفِ مشتری» (R219، بخشِ ۱۲ -- Customer 360). */
  onOpen360: () => void;
}

const CUSTOMER_TYPE_LABELS: Record<string, string> = {
  INDIVIDUAL: "شخص", COMPANY: "شرکت", STORE: "فروشگاه", ORGANIZATION: "سازمان",
  WHOLESALER: "عمده‌فروش", RETAILER: "خرده‌فروش", AGENT: "نماینده", ONLINE: "مشتریِ آنلاین",
};

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
  vanSales,
  salesMode,
  isManager,
  onOpenAddresses,
  onOpen360,
}: Props) {
  const { colors, spacing, typography } = useTheme();
  const [detail, setDetail] = useState<CustomerDetailResponse | null>(null);
  const [visitPlan, setVisitPlan] = useState<VisitPlanRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [printingId, setPrintingId] = useState<number | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [approving, setApproving] = useState(false);
  const toast = useToast();

  const approve = async () => {
    setApproving(true);
    try {
      await apiClient.approveCustomer(detailAccountId);
      toast.show("مشتری تایید شد.", "success");
      await load();
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "تاییدِ مشتری ناموفق بود.", "danger");
    } finally {
      setApproving(false);
    }
  };

  const reject = async () => {
    if (!rejectReason.trim()) return;
    setApproving(true);
    try {
      await apiClient.rejectCustomer(detailAccountId, rejectReason.trim());
      toast.show("مشتری رد شد.", "success");
      setRejectReason("");
      await load();
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "ردِ مشتری ناموفق بود.", "danger");
    } finally {
      setApproving(false);
    }
  };

  // طبقِ درخواستِ صریحِ کاربر («پرینتِ فاکتور و فایلِ pdf»): چاپِ دوبارهٔ
  // نسخهٔ رسمیِ هر سندِ اخیر از سرور (مثلاً فاکتوری که هنگامِ ثبت آفلاین بود).
  const printDocument = async (documentId: number, asPdf: boolean) => {
    setPrintingId(documentId);
    try {
      const data = await apiClient.getInvoicePrintData(documentId);
      await (asPdf ? shareInvoicePdf(data) : printInvoice(data));
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "چاپ انجام نشد.", "danger");
    } finally {
      setPrintingId(null);
    }
  };

  const load = useCallback(async () => {
    setError(null);
    try {
      const [data, cached] = await Promise.all([apiClient.getCustomerDetail(detailAccountId, salesMode), localCache.getPullResponse()]);
      setDetail(data);
      setVisitPlan(cached?.visit_plans.find((p) => p.customer_detail_account_id === detailAccountId) ?? null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافتِ اطلاعاتِ مشتری ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [apiClient, localCache, detailAccountId, salesMode]);

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
      <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />

      <View>
        <Text style={[typography.h2, { color: colors.textPrimary }]}>{detail.name}</Text>
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>{detail.code}</Text>
        {detail.status_code ? (
          <View style={{ marginTop: spacing.sm }}>
            <StatusBadge statusCode={detail.status_code} label={STATUS_LABELS[detail.status_code] ?? detail.status_code} />
          </View>
        ) : null}
        {detail.mobile ? (
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>موبایل: {detail.mobile}</Text>
        ) : null}
        {detail.customer_type_code || detail.customer_class ? (
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
            {[
              detail.customer_type_code ? CUSTOMER_TYPE_LABELS[detail.customer_type_code] ?? detail.customer_type_code : null,
              detail.customer_class ? `طبقه‌یِ ${detail.customer_class}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </Text>
        ) : null}
        {detail.notes ? (
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>یادداشت: {detail.notes}</Text>
        ) : null}
      </View>

      {isManager && detail.status_code === "PENDING_APPROVAL" ? (
        <Card>
          <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.sm }]}>تاییدِ مشتریِ جدید</Text>
          <Button label="تاییدِ مشتری" onPress={approve} loading={approving} />
          <Input
            label="دلیلِ رد (فقط اگر رد می‌کنید)"
            value={rejectReason}
            onChangeText={setRejectReason}
            placeholder="مثلاً: اطلاعات ناقص است"
            style={{ marginTop: spacing.sm }}
          />
          <Button label="ردِ مشتری" variant="danger" onPress={reject} loading={approving} disabled={!rejectReason.trim()} />
        </Card>
      ) : null}

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
        {!collectionOnly && !vanSales ? (
          <Button
            label="شروعِ ویزیت"
            fullWidth={false}
            disabled={visitPlan === null}
            onPress={() => visitPlan && onStartVisit(customerRow, visitPlan)}
          />
        ) : null}
        {!collectionOnly ? (
          <Button label={vanSales ? "صدورِ فاکتور" : "ثبتِ سفارش"} fullWidth={false} variant="secondary" onPress={() => onCreateOrder(customerRow)} />
        ) : null}
        <Button label="ثبتِ وصول" fullWidth={false} variant="secondary" onPress={() => onCreateCollection(customerRow)} />
        {detail.phone ? <Button label="تماس" fullWidth={false} variant="ghost" onPress={callCustomer} /> : null}
        {detail.gps_latitude || detail.address ? (
          <Button label="مسیریابی" fullWidth={false} variant="ghost" onPress={navigateToCustomer} />
        ) : null}
        <Button label="آدرس‌ها" fullWidth={false} variant="ghost" onPress={onOpenAddresses} />
        <Button label="نمایِ کامل (۳۶۰)" fullWidth={false} variant="ghost" onPress={onOpen360} />
      </View>
      {!collectionOnly && !vanSales && visitPlan === null ? (
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
                  alignItems: "center",
                  justifyContent: "space-between",
                  paddingVertical: spacing.xs,
                  borderTopWidth: index === 0 ? 0 : 1,
                  borderTopColor: colors.border,
                }}
              >
                <View style={{ flex: 1 }}>
                  <Text style={[typography.body, { color: colors.textPrimary }]}>
                    #{d.document_no} · {formatJalaliDate(d.document_date)}
                  </Text>
                  <Text style={[typography.numeric, { color: colors.textPrimary }]}>{formatAmount(d.total_amount)}</Text>
                </View>
                <Button label="چاپ" size="md" variant="ghost" fullWidth={false} disabled={printingId !== null} onPress={() => printDocument(d.document_id, false)} />
                <Button label="PDF" size="md" variant="ghost" fullWidth={false} disabled={printingId !== null} onPress={() => printDocument(d.document_id, true)} />
              </View>
            ))}
          </Card>
        </View>
      ) : null}
    </ScrollView>
  );
}
