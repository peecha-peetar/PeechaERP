import React, { useCallback, useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { PartyAddressRow } from "../api/types";
import { Button, Card, EmptyState, ErrorState, Input, SkeletonList, useToast } from "../components";
import { LocationProvider } from "../location";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  locationProvider: LocationProvider;
  detailAccountId: number;
  onBack: () => void;
}

const ADDRESS_TYPE_OPTIONS: { code: string; label: string }[] = [
  { code: "STORE", label: "فروشگاه" }, { code: "OFFICE", label: "دفتر" }, { code: "WAREHOUSE", label: "انبار" },
  { code: "DELIVERY", label: "تحویل" }, { code: "BILLING", label: "صورتحساب" }, { code: "RETURN", label: "مرجوعی" },
];
const ADDRESS_TYPE_LABELS: Record<string, string> = Object.fromEntries(ADDRESS_TYPE_OPTIONS.map((o) => [o.code, o.label]));

function TypeChip({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  const { colors, spacing, radius, typography } = useTheme();
  return (
    <Button
      label={label}
      size="md"
      fullWidth={false}
      variant={selected ? "primary" : "secondary"}
      onPress={onPress}
      style={{ marginEnd: spacing.xs, marginBottom: spacing.xs }}
    />
  );
}

/** طبقِ بازبینیِ ساختارِ «تعریفِ مشتری» (R216، بخشِ ۲ -- چندآدرسیِ واقعی
 * + GeoFend): برخلافِ آدرسِ تکیِ قدیمیِ رویِ خودِ مشتری، این‌جا هر آدرس
 * نوعِ خودش (فروشگاه/انبار/تحویل/...) + GPS/شعاعِ GeoFendِ مستقل دارد --
 * طبقِ اصلِ «هرگز عملیاتِ واقعی را برایِ آفلاین‌بودن رد نکن»، این صفحه
 * فقط آنلاین کار می‌کند (لیستِ آدرس‌ها همیشه از سرورِ زنده خوانده
 * می‌شود -- برخلافِ CREATE_CUSTOMER که در صفِ آفلاین صف می‌شود). */
export function CustomerAddressesScreen({ apiClient, locationProvider, detailAccountId, onBack }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [addresses, setAddresses] = useState<PartyAddressRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [typeCode, setTypeCode] = useState("STORE");
  const [line1, setLine1] = useState("");
  const [city, setCity] = useState("");
  const [geofenceRadius, setGeofenceRadius] = useState("");
  const [capturingGps, setCapturingGps] = useState(false);
  const [gpsCaptured, setGpsCaptured] = useState(false);
  const [saving, setSaving] = useState(false);
  const gpsRef = React.useRef<{ latitude: number; longitude: number } | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setAddresses(await apiClient.listCustomerAddresses(detailAccountId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافتِ آدرس‌ها ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [apiClient, detailAccountId]);

  useEffect(() => {
    load();
  }, [load]);

  const captureGps = async () => {
    setCapturingGps(true);
    try {
      const position = await locationProvider.getCurrentPosition();
      gpsRef.current = position;
      setGpsCaptured(position !== null);
    } finally {
      setCapturingGps(false);
    }
  };

  const resetForm = () => {
    setShowForm(false);
    setTypeCode("STORE");
    setLine1("");
    setCity("");
    setGeofenceRadius("");
    setGpsCaptured(false);
    gpsRef.current = null;
  };

  const save = async () => {
    if (!line1.trim()) {
      toast.show("متنِ آدرس الزامی است.", "danger");
      return;
    }
    setSaving(true);
    try {
      await apiClient.createCustomerAddress(detailAccountId, {
        address_type_code: typeCode,
        line1: line1.trim(),
        city: city.trim() || null,
        gps_latitude: gpsRef.current?.latitude ?? null,
        gps_longitude: gpsRef.current?.longitude ?? null,
        geofence_radius_meters: geofenceRadius.trim() ? Number(geofenceRadius.trim()) : null,
      });
      toast.show("آدرس ثبت شد.", "success");
      resetForm();
      await load();
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "ثبتِ آدرس ناموفق بود.", "danger");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (addressId: number) => {
    try {
      await apiClient.deleteCustomerAddress(detailAccountId, addressId);
      toast.show("آدرس حذف شد.", "success");
      await load();
    } catch (e) {
      toast.show(e instanceof ApiError ? e.message : "حذفِ آدرس ناموفق بود.", "danger");
    }
  };

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.md, backgroundColor: colors.background }}>
      <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
      <Text style={[typography.h2, { color: colors.textPrimary }]}>آدرس‌هایِ مشتری</Text>

      {loading ? (
        <SkeletonList count={3} />
      ) : error ? (
        <ErrorState description={error} onRetry={load} />
      ) : (
        <>
          {addresses.length === 0 ? (
            <EmptyState title="آدرسی ثبت نشده" description="اولین آدرس را از دکمه‌یِ پایین اضافه کنید." />
          ) : (
            addresses.map((a) => (
              <Card key={a.address_id}>
                <Text style={[typography.captionBold, { color: colors.textPrimary }]}>
                  {ADDRESS_TYPE_LABELS[a.address_type_code] ?? a.address_type_code}
                  {a.is_default ? " (پیش‌فرض)" : ""}
                </Text>
                <Text style={[typography.body, { color: colors.textPrimary, marginTop: spacing.xs }]}>{a.line1}</Text>
                {a.city ? <Text style={[typography.caption, { color: colors.textSecondary }]}>{a.city}</Text> : null}
                {a.gps_latitude && a.gps_longitude ? (
                  <Text style={[typography.caption, { color: colors.textSecondary }]}>
                    موقعیتِ مکانی ثبت‌شده{a.geofence_radius_meters ? ` · شعاعِ مجاز: ${a.geofence_radius_meters} متر` : ""}
                  </Text>
                ) : null}
                <Button label="حذف" size="md" variant="ghost" fullWidth={false} onPress={() => remove(a.address_id)} style={{ marginTop: spacing.sm }} />
              </Card>
            ))
          )}

          {showForm ? (
            <Card>
              <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }]}>نوعِ آدرس</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", marginBottom: spacing.sm }}>
                {ADDRESS_TYPE_OPTIONS.map((o) => (
                  <TypeChip key={o.code} label={o.label} selected={typeCode === o.code} onPress={() => setTypeCode(o.code)} />
                ))}
              </View>
              <Input label="متنِ آدرس *" value={line1} onChangeText={setLine1} multiline />
              <Input label="شهر" value={city} onChangeText={setCity} />
              <Input
                label="شعاعِ GeoFend به متر (اختیاری -- محدودیتِ ثبتِ ویزیت)"
                value={geofenceRadius}
                onChangeText={setGeofenceRadius}
                keyboardType="number-pad"
              />
              <Text style={[typography.body, { color: gpsCaptured ? colors.success : colors.textSecondary, marginBottom: spacing.sm }]}>
                {gpsCaptured ? "موقعیتِ مکانی ثبت شد" : "موقعیتِ مکانی ثبت نشده"}
              </Text>
              <Button label="ثبتِ موقعیتِ مکانی" variant="secondary" onPress={captureGps} loading={capturingGps} style={{ marginBottom: spacing.sm }} />
              <Button label="ذخیره‌یِ آدرس" onPress={save} loading={saving} disabled={!line1.trim()} />
              <Button label="انصراف" variant="ghost" onPress={resetForm} style={{ marginTop: spacing.sm }} />
            </Card>
          ) : (
            <Button label="افزودنِ آدرس" variant="secondary" onPress={() => setShowForm(true)} />
          )}
        </>
      )}
    </ScrollView>
  );
}
