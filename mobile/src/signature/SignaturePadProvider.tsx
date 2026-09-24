import React, { createContext, useCallback, useContext, useRef, useState } from "react";
import { Modal, Text, View } from "react-native";
import SignatureCanvas, { SignatureViewRef } from "react-native-signature-canvas";
import { Button } from "../components";
import { useTheme } from "../theme/ThemeProvider";

type Resolver = (value: string | null) => void;

interface SignaturePadContextValue {
  requestSignature: () => Promise<string | null>;
}

const SignaturePadContext = createContext<SignaturePadContextValue | null>(null);

/** طبقِ قراردادِ peecha_api.routers.delivery: همیشه رشته‌یِ base64ِ خامِ
 * فایل (بدونِ پیشوندِ data:...;base64,) -- خروجیِ onOKِ کتابخانه یک
 * data URLِ کاملِ image/png است. */
function stripDataUrlPrefix(dataUrl: string): string {
  const commaIndex = dataUrl.indexOf(",");
  return commaIndex === -1 ? dataUrl : dataUrl.slice(commaIndex + 1);
}

/** طبقِ محدودیتِ مستندشده در capture.ts (ExpoCaptureProvider): بر خلافِ
 * دوربین که رابطِ تمام‌صفحه‌یِ نیتیوِ خودش را دارد و با یک Promiseِ ساده
 * برمی‌گردد، امضا نیازمندِ یک کانواسِ لمسیِ دائمی در درختِ کامپوننت است.
 * این Provider همان پُلِ لازم است: یک Modal که با requestSignature()
 * به‌صورتِ imperative (از دلِ یک کلاسِ سادهٔ غیرِReact مثلِ
 * ExpoCaptureProvider) باز می‌شود و با تاییدِ کاربر/پاک‌بودن/انصراف،
 * دقیقاً یک‌بار Promise را resolve می‌کند. */
export function SignaturePadProvider({ children }: { children: React.ReactNode }) {
  const { colors, spacing, typography } = useTheme();
  const [visible, setVisible] = useState(false);
  const resolverRef = useRef<Resolver | null>(null);
  const canvasRef = useRef<SignatureViewRef>(null);

  const finish = useCallback((value: string | null) => {
    setVisible(false);
    resolverRef.current?.(value);
    resolverRef.current = null;
  }, []);

  const requestSignature = useCallback((): Promise<string | null> => {
    return new Promise((resolve) => {
      resolverRef.current = resolve;
      setVisible(true);
    });
  }, []);

  return (
    <SignaturePadContext.Provider value={{ requestSignature }}>
      {children}
      <Modal visible={visible} animationType="slide" onRequestClose={() => finish(null)}>
        <View style={{ flex: 1, backgroundColor: colors.background }}>
          <View
            style={{
              flexDirection: "row", justifyContent: "space-between", alignItems: "center",
              padding: spacing.lg,
            }}
          >
            <Text style={[typography.h3, { color: colors.textPrimary }]}>امضایِ تحویل‌گیرنده</Text>
            <Button label="انصراف" variant="ghost" fullWidth={false} onPress={() => finish(null)} />
          </View>
          {/* طبقِ گزارشِ واقعیِ کاربر («بعد از امضا جایی برایِ تایید نبود»):
              دکمه‌هایِ داخلیِ خودِ کتابخانه (که درونِ WebView رندر
              می‌شوند) گاهی رویِ گوشی‌هایِ واقعی دیده/لمس نمی‌شوند --
              پس این‌جا دکمه‌هایِ خودمان (کاملاً بیرونِ WebView، تضمیناً
              قابلِ‌دیدن) اضافه شد و از طریقِ ref صدا زده می‌شوند. */}
          <View style={{ flex: 1 }}>
            <SignatureCanvas
              ref={canvasRef}
              onOK={(dataUrl: string) => finish(stripDataUrlPrefix(dataUrl))}
              onEmpty={() => finish(null)}
              descriptionText="این‌جا امضا کنید"
              penColor="#111827"
              backgroundColor="#ffffff"
              webStyle=".m-signature-pad--footer { display: none; margin: 0; }"
            />
          </View>
          <View style={{ flexDirection: "row", gap: spacing.sm, padding: spacing.lg }}>
            <Button
              label="پاک‌کردن"
              variant="secondary"
              fullWidth={false}
              onPress={() => canvasRef.current?.clearSignature()}
            />
            <View style={{ flex: 1 }}>
              <Button label="تاییدِ امضا" onPress={() => canvasRef.current?.readSignature()} />
            </View>
          </View>
        </View>
      </Modal>
    </SignaturePadContext.Provider>
  );
}

export function useSignaturePad(): SignaturePadContextValue {
  const ctx = useContext(SignaturePadContext);
  if (!ctx) throw new Error("useSignaturePad باید داخلِ SignaturePadProvider استفاده شود.");
  return ctx;
}
