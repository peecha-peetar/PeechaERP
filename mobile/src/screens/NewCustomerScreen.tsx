import React, { useEffect, useState } from "react";
import { ScrollView, Text, TouchableOpacity, View } from "react-native";
import { ApiClient, ApiError } from "../api/client";
import { CustomerGroupRow } from "../api/types";
import { CaptureProvider } from "../capture";
import { Button, Card, Input, useToast } from "../components";
import { LocationProvider } from "../location";
import { OfflineQueue } from "../sync/offlineQueue";
import { useTheme } from "../theme/ThemeProvider";

interface Props {
  apiClient: ApiClient;
  offlineQueue: OfflineQueue;
  locationProvider: LocationProvider;
  captureProvider: CaptureProvider;
  onDone: () => void;
}

function GroupChip({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  const { colors, spacing, radius, typography } = useTheme();
  return (
    <TouchableOpacity
      onPress={onPress}
      style={{
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.xs,
        borderRadius: radius.md,
        borderWidth: 1.5,
        borderColor: selected ? colors.primary : colors.border,
        backgroundColor: selected ? colors.primary : "transparent",
      }}
    >
      <Text style={[typography.caption, { color: selected ? colors.textInverse : colors.textPrimary }]}>{label}</Text>
    </TouchableOpacity>
  );
}

/** طبقِ Customer Acquisition (Phase 9 سندِ اصلی) + درخواستِ کاربر («با
 * حفظِ ساختارِ فعلی همه‌یِ این امکاناتو داشته باشه»): فرمِ ثبتِ مشتریِ
 * جدید در موبایل -- آفلاین‌اول (اقدام همیشه به صفِ محلی می‌رود، طبقِ
 * الگویِ همینِ START_VISIT/CREATE_ORDER). کدِ مشتری و مصوبه (approve)
 * سمتِ سرور است -- این‌جا فقط پیشنهادِ کد (وقتی آنلاین) برایِ اطمینانِ
 * ویزیتور نمایش داده می‌شود، نه ارسال. */
export function NewCustomerScreen({ apiClient, offlineQueue, locationProvider, captureProvider, onDone }: Props) {
  const { colors, spacing, typography } = useTheme();
  const toast = useToast();
  const [suggestedCode, setSuggestedCode] = useState<string | null>(null);
  const [groups, setGroups] = useState<CustomerGroupRow[]>([]);
  const [name, setName] = useState("");
  const [mobile, setMobile] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [notes, setNotes] = useState("");
  const [groupId, setGroupId] = useState<number | null>(null);
  const [photoBase64, setPhotoBase64] = useState<string | null>(null);
  const [capturingPhoto, setCapturingPhoto] = useState(false);
  const [capturingGps, setCapturingGps] = useState(false);
  const [gpsCaptured, setGpsCaptured] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const gpsRef = React.useRef<{ latitude: number; longitude: number } | null>(null);

  useEffect(() => {
    apiClient
      .getNewCustomerFormOptions()
      .then((options) => {
        setSuggestedCode(options.suggested_code);
        setGroups(options.groups);
      })
      .catch(() => {
        // آفلاین یا خطایِ شبکه: فرم بدونِ کدِ پیشنهادی/فهرستِ گروه هم
        // قابلِ‌ثبت است -- طبقِ نیازِ صریحِ «Customer Acquisition باید
        // آفلاین هم کار کند».
      });
  }, [apiClient]);

  const capturePhoto = async () => {
    setCapturingPhoto(true);
    try {
      const photo = await captureProvider.capturePhoto();
      setPhotoBase64(photo);
    } finally {
      setCapturingPhoto(false);
    }
  };

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

  const submit = async () => {
    if (!name.trim()) {
      toast.show("نامِ مشتری الزامی است.", "danger");
      return;
    }
    setSubmitting(true);
    try {
      await offlineQueue.enqueue({
        type: "CREATE_CUSTOMER",
        payload: {
          name: name.trim(),
          customer_group_id: groupId,
          address: address.trim() || null,
          phone: phone.trim() || null,
          mobile: mobile.trim() || null,
          notes: notes.trim() || null,
          photo_base64: photoBase64,
          gps_latitude: gpsRef.current?.latitude ?? null,
          gps_longitude: gpsRef.current?.longitude ?? null,
        },
      });
      toast.show("مشتری ثبت شد و برایِ تاییدِ سرپرست ارسال می‌شود.", "success");
      onDone();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.md, backgroundColor: colors.background }}>
      <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onDone} />
      <Text style={[typography.h2, { color: colors.textPrimary }]}>ثبتِ مشتریِ جدید</Text>
      {suggestedCode ? (
        <Text style={[typography.caption, { color: colors.textSecondary }]}>کدِ پیشنهادی: {suggestedCode}</Text>
      ) : null}

      <Input label="نامِ مشتری *" value={name} onChangeText={setName} placeholder="نامِ فروشگاه/مشتری" />
      <Input label="موبایل" value={mobile} onChangeText={setMobile} keyboardType="phone-pad" />
      <Input label="تلفن" value={phone} onChangeText={setPhone} keyboardType="phone-pad" />
      <Input label="آدرس" value={address} onChangeText={setAddress} multiline />
      <Input label="یادداشت (اختیاری)" value={notes} onChangeText={setNotes} multiline />

      {groups.length > 0 ? (
        <View>
          <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: spacing.xs }]}>گروهِ مشتری</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
            {groups.map((g) => (
              <GroupChip key={g.group_id} label={g.name} selected={groupId === g.group_id} onPress={() => setGroupId(groupId === g.group_id ? null : g.group_id)} />
            ))}
          </View>
        </View>
      ) : null}

      <Card>
        <Text style={[typography.body, { color: gpsCaptured ? colors.success : colors.textSecondary }]}>
          {gpsCaptured ? "موقعیتِ مکانی ثبت شد" : "موقعیتِ مکانی ثبت نشده"}
        </Text>
        <Button label="ثبتِ موقعیتِ مکانی" variant="secondary" onPress={captureGps} loading={capturingGps} style={{ marginTop: spacing.sm }} />
      </Card>

      <Button
        label={photoBase64 ? "عکس گرفته شد (دوباره بگیر)" : "گرفتنِ عکس (اختیاری)"}
        variant="secondary"
        onPress={capturePhoto}
        loading={capturingPhoto}
      />

      <Button label="ثبتِ مشتری" onPress={submit} loading={submitting} disabled={!name.trim()} />
    </ScrollView>
  );
}
