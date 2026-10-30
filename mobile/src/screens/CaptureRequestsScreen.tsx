import React, { useCallback, useEffect, useRef, useState } from "react";
import { Alert, FlatList, Image, RefreshControl, ScrollView, Text, View } from "react-native";
import * as ImageManipulator from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import { ApiClient, ApiError } from "../api/client";
import { CaptureRequestRow } from "../api/types";
import { Button, Card, EmptyState, ErrorState, SkeletonList, StatusBadge, useToast } from "../components";
import {
  addPhoto, CaptureDraft, canAddPhoto, DraftPhoto, isOpenStatus, newDraft, removePhoto, replacePhoto, toPayload,
} from "../dms/captureDraft";
import { formatJalaliDateTime } from "../jalali";
import { useTheme } from "../theme/ThemeProvider";

/** عکسِ سند باید خوانا بماند ولی بی‌دلیل سنگین نباشد. */
const MAX_SIDE_PX = 2000;

function badgeCode(status: string): string {
  if (status === "COMPLETED") return "DONE";
  return status === "OPENED" || status === "CAPTURING" || status === "UPLOADING" ? "IN_PROGRESS" : status;
}

interface Props {
  apiClient: ApiClient;
  /** وقتی از اعلان باز می‌شود، همان درخواست مستقیم باز شود. */
  initialRequestId?: number;
  onBack: () => void;
}

async function takePhoto(): Promise<DraftPhoto | null> {
  const permission = await ImagePicker.requestCameraPermissionsAsync();
  if (!permission.granted) throw new Error("اجازهٔ دوربین داده نشده است. از تنظیمات گوشی اجازه دهید.");
  const result = await ImagePicker.launchCameraAsync({ quality: 0.9, mediaTypes: "images", exif: false });
  if (result.canceled) return null;
  const asset = result.assets[0];
  if (!asset?.uri) return null;
  const longSide = Math.max(asset.width ?? 0, asset.height ?? 0);
  const resize =
    longSide > MAX_SIDE_PX ? [{ resize: (asset.width ?? 0) >= (asset.height ?? 0) ? { width: MAX_SIDE_PX } : { height: MAX_SIDE_PX } }] : [];
  // خروجیِ دوباره‌ساخته EXIF (از جمله موقعیت مکانی) ندارد
  const out = await ImageManipulator.manipulateAsync(asset.uri, resize, {
    compress: 0.85,
    format: ImageManipulator.SaveFormat.JPEG,
    base64: true,
  });
  return out.base64 ? { uri: out.uri, base64: out.base64 } : null;
}

/** درخواست‌های عکس‌برداری که از کامپیوتر برای همین کاربر ساخته شده: دوربین، پیش‌نمایش، حذف و
 * گرفتن دوباره، ارسال با درصد پیشرفت و لغو. پس از ارسال، عکس‌ها خودکار به همان رکورد پیوست می‌شوند. */
export function CaptureRequestsScreen({ apiClient, initialRequestId, onBack }: Props) {
  const { colors, spacing, radius, typography } = useTheme();
  const toast = useToast();
  const [items, setItems] = useState<CaptureRequestRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<CaptureRequestRow | null>(null);
  const [draft, setDraft] = useState<CaptureDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const autoOpened = useRef(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setItems(await apiClient.listCaptureRequests());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "دریافت درخواست‌ها ناموفق بود.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiClient]);

  useEffect(() => {
    load();
  }, [load]);

  const open = useCallback(
    async (requestId: number) => {
      setBusy(true);
      setMessage(null);
      setDone(false);
      try {
        const row = await apiClient.openCaptureRequest(requestId);
        setActive(row);
        setDraft(newDraft(row.request_id, row.max_photos));
      } catch (e) {
        Alert.alert("بازکردن درخواست", e instanceof ApiError ? e.message : "ارتباط با سرور برقرار نشد.");
        load();
      } finally {
        setBusy(false);
      }
    },
    [apiClient, load],
  );

  useEffect(() => {
    if (!initialRequestId || autoOpened.current || loading) return;
    autoOpened.current = true;
    open(initialRequestId);
  }, [initialRequestId, loading, open]);

  const backToList = () => {
    setActive(null);
    setDraft(null);
    setProgress(null);
    setMessage(null);
    setDone(false);
    load();
  };

  const capture = async (replaceIndex?: number) => {
    if (!active || !draft) return;
    setMessage(null);
    try {
      if (draft.photos.length === 0 && replaceIndex === undefined) {
        apiClient.markCaptureCapturing(active.request_id).catch(() => undefined);
      }
      const photo = await takePhoto();
      if (!photo) return;
      setDraft((current) =>
        current ? (replaceIndex === undefined ? addPhoto(current, photo) : replacePhoto(current, replaceIndex, photo)) : current,
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "دوربین باز نشد.");
    }
  };

  const send = async () => {
    if (!active || !draft || draft.photos.length === 0) return;
    setBusy(true);
    setMessage(null);
    setProgress(0);
    try {
      const row = await apiClient.uploadCapturePhotos(active.request_id, toPayload(draft), draft.uploadKey, setProgress);
      setActive(row);
      setDone(true);
      toast.show("عکس‌ها به سند پیوست شد.", "success");
    } catch (e) {
      // کلید ثابت می‌ماند تا تلاش دوباره، اگر ارسال قبلی رسیده بود، پیوست تکراری نسازد
      setMessage(e instanceof ApiError ? e.message : "ارسال انجام نشد. اتصال را بررسی کنید و دوباره بفرستید.");
      if (e instanceof ApiError && (e.status === 409 || e.status === 410 || e.status === 404)) {
        apiClient.openCaptureRequest(active.request_id).then(setActive).catch(() => undefined);
      }
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };

  const cancelRequest = () => {
    if (!active) return;
    Alert.alert("لغو درخواست", "این درخواست عکس‌برداری لغو شود؟", [
      { text: "نه", style: "cancel" },
      {
        text: "لغو شود",
        style: "destructive",
        onPress: async () => {
          try {
            await apiClient.cancelCaptureRequest(active.request_id);
            toast.show("درخواست لغو شد.", "info");
            backToList();
          } catch (e) {
            setMessage(e instanceof ApiError ? e.message : "لغو انجام نشد.");
          }
        },
      },
    ]);
  };

  if (active && draft) {
    const open_ = isOpenStatus(active.status) && !done;
    return (
      <ScrollView style={{ flex: 1, backgroundColor: colors.background }} contentContainerStyle={{ padding: spacing.lg, gap: spacing.md }}>
        <Button label="بازگشت به فهرست" variant="ghost" fullWidth={false} onPress={backToList} disabled={busy} />
        <Text style={[typography.h2, { color: colors.textPrimary }]}>عکس‌برداری برای سند</Text>
        <Card>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>{active.target_kind}</Text>
          <Text style={[typography.bodyBold, { color: colors.textPrimary, marginTop: 2 }]}>{active.target_label}</Text>
          <View style={{ flexDirection: "row-reverse", justifyContent: "space-between", alignItems: "center", marginTop: spacing.sm }}>
            <StatusBadge statusCode={done ? "DONE" : badgeCode(active.status)} label={done ? "پیوست شد" : active.status_label} />
            {active.expires_at && open_ ? (
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                مهلت تا {formatJalaliDateTime(active.expires_at)}
              </Text>
            ) : null}
          </View>
        </Card>

        {done ? (
          <Card style={{ backgroundColor: colors.successSoft, borderColor: colors.success }}>
            <Text style={[typography.bodyBold, { color: colors.success }]}>
              عکس‌ها فرستاده شد و به سند پیوست شد. روی کامپیوتر هم دیده می‌شود.
            </Text>
          </Card>
        ) : !open_ ? (
          <Card style={{ backgroundColor: colors.warningSoft, borderColor: colors.warning }}>
            <Text style={[typography.bodyBold, { color: colors.textPrimary }]}>
              این درخواست دیگر باز نیست ({active.status_label}). از کامپیوتر درخواست جدید بسازید.
            </Text>
          </Card>
        ) : (
          <Text style={[typography.body, { color: colors.textSecondary }]}>
            حداکثر {draft.maxPhotos} عکس. پیش از ارسال می‌توانید هر عکس را ببینید، حذف کنید یا دوباره بگیرید.
          </Text>
        )}

        {draft.photos.map((photo, index) => (
          <Card key={`${index}-${photo.uri}`}>
            <Image
              source={{ uri: photo.uri }}
              style={{ width: "100%", aspectRatio: 3 / 4, borderRadius: radius.md, backgroundColor: colors.surfaceAlt }}
              resizeMode="contain"
              accessibilityLabel={`عکس ${index + 1}`}
            />
            {open_ ? (
              <View style={{ flexDirection: "row-reverse", gap: spacing.sm, marginTop: spacing.sm }}>
                <View style={{ flex: 1 }}>
                  <Button label="گرفتن دوباره" variant="secondary" size="md" onPress={() => capture(index)} disabled={busy} />
                </View>
                <View style={{ flex: 1 }}>
                  <Button label="حذف" variant="ghost" size="md" onPress={() => setDraft(removePhoto(draft, index))} disabled={busy} />
                </View>
              </View>
            ) : null}
          </Card>
        ))}

        {message ? <Text style={[typography.body, { color: colors.danger }]}>{message}</Text> : null}
        {progress !== null ? (
          <View style={{ gap: spacing.xs }}>
            <View style={{ height: 8, borderRadius: 4, backgroundColor: colors.surfaceAlt, overflow: "hidden" }}>
              <View style={{ width: `${progress}%`, height: 8, backgroundColor: colors.primary }} />
            </View>
            <Text style={[typography.caption, { color: colors.textSecondary }]}>در حال ارسال: {progress}٪</Text>
          </View>
        ) : null}

        {open_ ? (
          <>
            <Button
              label={draft.photos.length ? "گرفتن عکس دیگر" : "بازکردن دوربین"}
              variant={draft.photos.length ? "secondary" : "primary"}
              onPress={() => capture()}
              disabled={busy || !canAddPhoto(draft)}
            />
            <Button
              label={draft.photos.length > 1 ? `ارسال ${draft.photos.length} عکس` : "ارسال عکس"}
              onPress={send}
              loading={busy && progress !== null}
              disabled={busy || draft.photos.length === 0}
            />
            <Button label="لغو درخواست" variant="danger" onPress={cancelRequest} disabled={busy} />
          </>
        ) : (
          <Button label="بازگشت به فهرست" onPress={backToList} />
        )}
      </ScrollView>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, padding: spacing.lg }}>
      <Button label="بازگشت" variant="ghost" fullWidth={false} onPress={onBack} />
      <Text style={[typography.h2, { color: colors.textPrimary, marginTop: spacing.sm }]}>عکس‌برداری برای اسناد</Text>
      <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2, marginBottom: spacing.md }]}>
        درخواست‌هایی که از کامپیوتر برای شما ساخته شده است.
      </Text>
      {loading ? (
        <SkeletonList count={3} />
      ) : error ? (
        <ErrorState description={error} onRetry={load} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(item) => String(item.request_id)}
          contentContainerStyle={{ gap: spacing.sm }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <Card onPress={busy ? undefined : () => open(item.request_id)}>
              <Text style={[typography.caption, { color: colors.textSecondary }]}>{item.target_kind}</Text>
              <Text style={[typography.bodyBold, { color: colors.textPrimary, marginTop: 2 }]}>{item.target_label}</Text>
              <View style={{ flexDirection: "row-reverse", justifyContent: "space-between", alignItems: "center", marginTop: spacing.sm }}>
                <StatusBadge statusCode={badgeCode(item.status)} label={item.status_label} />
                {item.expires_at ? (
                  <Text style={[typography.caption, { color: colors.textSecondary }]}>
                    مهلت تا {formatJalaliDateTime(item.expires_at)}
                  </Text>
                ) : null}
              </View>
            </Card>
          )}
          ListEmptyComponent={
            <EmptyState title="درخواست بازی نیست" description="روی کامپیوتر، در فرم سند یا رکورد، «عکس با موبایل» را بزنید." />
          }
        />
      )}
    </View>
  );
}
