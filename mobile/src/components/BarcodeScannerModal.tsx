import { CameraView, useCameraPermissions } from "expo-camera";
import React, { useRef } from "react";
import { Modal, StyleSheet, Text, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";
import { Button } from "./Button";

interface Props {
  visible: boolean;
  onClose: () => void;
  /** هر بار که یک بارکدِ تازه خوانده می‌شود. اسکنر باز می‌ماند تا
   * ویزیتور چند کالا را پشتِ‌سرِهم اسکن کند. */
  onScanned: (code: string) => void;
}

// همان بارکد تا این مدت دوباره پذیرفته نمی‌شود -- دوربین یک بارکد را در
// هر ثانیه چند بار می‌خواند و بدونِ این، یک اسکن چند عدد اضافه می‌کرد.
const REPEAT_COOLDOWN_MS = 1500;

export function BarcodeScannerModal({ visible, onClose, onScanned }: Props) {
  const { colors, spacing, typography } = useTheme();
  const [permission, requestPermission] = useCameraPermissions();
  const lastScan = useRef<{ code: string; at: number } | null>(null);

  const handleScan = ({ data }: { data: string }) => {
    const now = Date.now();
    if (lastScan.current && lastScan.current.code === data && now - lastScan.current.at < REPEAT_COOLDOWN_MS) return;
    lastScan.current = { code: data, at: now };
    onScanned(data);
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        {permission?.granted ? (
          <CameraView
            style={StyleSheet.absoluteFill}
            facing="back"
            barcodeScannerSettings={{
              barcodeTypes: ["ean13", "ean8", "upc_a", "upc_e", "code128", "code39", "code93", "itf14", "qr", "datamatrix"],
            }}
            onBarcodeScanned={handleScan}
          />
        ) : (
          <View style={{ flex: 1, justifyContent: "center", padding: spacing.xl, gap: spacing.lg }}>
            <Text style={[typography.body, { color: colors.textPrimary, textAlign: "center" }]}>
              برایِ اسکنِ بارکد، دسترسیِ دوربین لازم است.
            </Text>
            <Button label="اجازهٔ دسترسی به دوربین" onPress={requestPermission} />
          </View>
        )}
        <View style={{ position: "absolute", bottom: spacing.xl, left: spacing.lg, right: spacing.lg, gap: spacing.sm }}>
          {permission?.granted ? (
            <Text style={[typography.bodyBold, { color: "#fff", textAlign: "center", backgroundColor: "rgba(0,0,0,0.55)", padding: spacing.sm, borderRadius: 8 }]}>
              بارکدِ کالا را جلویِ دوربین بگیرید
            </Text>
          ) : null}
          <Button label="پایانِ اسکن" variant="secondary" onPress={onClose} />
        </View>
      </View>
    </Modal>
  );
}
