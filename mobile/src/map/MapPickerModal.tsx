import React, { useMemo, useRef } from "react";
import { Modal, Text, View } from "react-native";
import { WebView, WebViewMessageEvent } from "react-native-webview";
import { Button } from "../components";
import { useTheme } from "../theme/ThemeProvider";
import { LEAFLET_CSS, LEAFLET_JS } from "./leafletAssets";
import { MARKER_ICON, MARKER_ICON_2X, MARKER_SHADOW } from "./markerIcons";

interface Props {
  visible: boolean;
  initialLatitude: number | null;
  initialLongitude: number | null;
  onCancel: () => void;
  onConfirm: (latitude: number, longitude: number) => void;
}

// طبقِ نبودِ زیرساختِ نقشه‌یِ داخلیِ ایران در این پروژه: مرکزِ پیش‌فرض
// (وقتی مختصاتِ قبلی موجود نیست) تهران است.
const DEFAULT_LAT = 35.6892;
const DEFAULT_LON = 51.389;

function buildHtml(lat: number, lon: number, zoom: number): string {
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
<style>${LEAFLET_CSS}
html, body, #map { height: 100%; margin: 0; padding: 0; }</style>
</head>
<body>
<div id="map"></div>
<script>${LEAFLET_JS}</script>
<script>
  L.Icon.Default.mergeOptions({
    iconUrl: "${MARKER_ICON}",
    iconRetinaUrl: "${MARKER_ICON_2X}",
    shadowUrl: "${MARKER_SHADOW}"
  });
  var map = L.map('map').setView([${lat}, ${lon}], ${zoom});
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);
  var marker = L.marker([${lat}, ${lon}], { draggable: true }).addTo(map);
  window.currentLatLng = { lat: ${lat}, lng: ${lon} };
  marker.on('dragend', function() { window.currentLatLng = marker.getLatLng(); });
  map.on('click', function(e) {
    marker.setLatLng(e.latlng);
    window.currentLatLng = { lat: e.latlng.lat, lng: e.latlng.lng };
  });
</script>
</body>
</html>`;
}

/** طبقِ بازخوردِ کاربر رویِ R220 («ثبتِ مختصات باید رویِ نقشه باشد، نه
 * تایپِ عدد»): انتخابِ مختصات با کلیک/درگ رویِ نقشه‌یِ OpenStreetMap
 * (Leaflet، به‌صورتِ کاملاً محلی درونِ HTML اینلاین شده -- فقط خودِ
 * کاشی‌هایِ نقشه نیازمندِ اینترنت‌اند، نه کتابخانه یا آیکنِ نشانگر).
 * برایِ ویزیتورِ حاضر در محل، دکمه‌یِ «موقعیتِ فعلی» در خودِ صفحه‌یِ
 * فراخوان (locationProvider) جداگانه می‌ماند؛ این مودال برایِ اصلاحِ
 * دستیِ نقطه رویِ نقشه است. */
export function MapPickerModal({ visible, initialLatitude, initialLongitude, onCancel, onConfirm }: Props) {
  const { colors, spacing, typography } = useTheme();
  const webViewRef = useRef<WebView>(null);

  const html = useMemo(() => {
    const lat = initialLatitude ?? DEFAULT_LAT;
    const lon = initialLongitude ?? DEFAULT_LON;
    const zoom = initialLatitude !== null ? 15 : 11;
    return buildHtml(lat, lon, zoom);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const handleConfirmPress = () => {
    webViewRef.current?.injectJavaScript(
      "window.ReactNativeWebView.postMessage(JSON.stringify(window.currentLatLng)); true;",
    );
  };

  const handleMessage = (event: WebViewMessageEvent) => {
    try {
      const data = JSON.parse(event.nativeEvent.data);
      if (typeof data.lat === "number" && typeof data.lng === "number") {
        onConfirm(data.lat, data.lng);
      }
    } catch {
      // پیامِ نامعتبر -- نادیده گرفته می‌شود.
    }
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onCancel}>
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <View style={{ padding: spacing.lg, paddingBottom: spacing.sm }}>
          <Text style={[typography.h3, { color: colors.textPrimary }]}>انتخابِ موقعیتِ مکانی رویِ نقشه</Text>
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: spacing.xs }]}>
            رویِ نقشه ضربه بزنید یا نشانگر را جابه‌جا کنید، سپس «تایید» را بزنید.
          </Text>
        </View>
        {visible ? (
          <WebView
            ref={webViewRef}
            originWhitelist={["*"]}
            source={{ html }}
            style={{ flex: 1 }}
            onMessage={handleMessage}
          />
        ) : null}
        <View style={{ flexDirection: "row", padding: spacing.lg, gap: spacing.sm }}>
          <Button label="تایید" onPress={handleConfirmPress} style={{ flex: 1 }} />
          <Button label="انصراف" variant="ghost" onPress={onCancel} style={{ flex: 1 }} />
        </View>
      </View>
    </Modal>
  );
}
