import React, { createContext, useCallback, useContext, useRef, useState } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";
import { toneColor, StatusTone } from "../theme/statusColors";

interface ToastMessage {
  id: number;
  text: string;
  tone: StatusTone;
}

interface ToastContextValue {
  show: (text: string, tone?: StatusTone) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let nextId = 1;

/** طبقِ اصلِ صریح («Toast»): پیامِ کوتاهِ ناپدیدشونده برایِ تاییدِ
 * عملیات (مثلِ «سفارش ثبت شد») -- بدونِ نیاز به کتابخانه‌یِ نیتیوِ
 * تازه، فقط Animated+View. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [message, setMessage] = useState<ToastMessage | null>(null);
  const opacity = useRef(new Animated.Value(0)).current;

  const show = useCallback(
    (text: string, tone: StatusTone = "neutral") => {
      const id = nextId++;
      setMessage({ id, text, tone });
      opacity.setValue(0);
      Animated.sequence([
        Animated.timing(opacity, { toValue: 1, duration: 200, useNativeDriver: true }),
        Animated.delay(2200),
        Animated.timing(opacity, { toValue: 0, duration: 250, useNativeDriver: true }),
      ]).start(({ finished }) => {
        if (finished) setMessage((current) => (current?.id === id ? null : current));
      });
    },
    [opacity],
  );

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      {message ? <ToastView message={message} opacity={opacity} /> : null}
    </ToastContext.Provider>
  );
}

function ToastView({ message, opacity }: { message: ToastMessage; opacity: Animated.Value }) {
  const { colors, spacing, radius, typography } = useTheme();
  const { bg, fg } = toneColor(message.tone, colors);
  return (
    <Animated.View
      pointerEvents="none"
      style={[
        styles.container,
        { opacity, backgroundColor: bg, borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
      ]}
    >
      <Text style={[typography.bodyBold, { color: fg, textAlign: "center" }]}>{message.text}</Text>
    </Animated.View>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast باید داخلِ ToastProvider استفاده شود.");
  return ctx;
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    start: 16,
    end: 16,
    bottom: 96,
  },
});
