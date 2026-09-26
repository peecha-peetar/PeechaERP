import React from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { useTheme } from "../theme/ThemeProvider";

interface BottomSheetProps {
  visible: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
}

/** طبقِ اصلِ صریح («Modal/Bottom Sheet»): برایِ اقداماتِ کوتاهِ داخلِ
 * صفحه (مثلاً انتخابِ روشِ وصول، ثبتِ یادداشت) بدونِ رفتن به صفحه‌یِ
 * تازه -- طبقِ اصلِ «کمترین کلیک». از Modal بومیِ RN استفاده می‌شود
 * (بدونِ کتابخانه‌یِ نیتیوِ تازه). */
export function BottomSheet({ visible, onClose, title, children }: BottomSheetProps) {
  const { colors, spacing, radius, typography } = useTheme();
  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={[styles.backdrop, { backgroundColor: colors.overlay }]} onPress={onClose} />
      <View style={[styles.sheet, { backgroundColor: colors.surface, borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl, padding: spacing.lg }]}>
        <View style={[styles.handle, { backgroundColor: colors.border }]} />
        {title ? <Text style={[typography.h3, { color: colors.textPrimary, marginBottom: spacing.md }]}>{title}</Text> : null}
        {children}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1 },
  sheet: { position: "absolute", start: 0, end: 0, bottom: 0 },
  handle: { width: 40, height: 4, borderRadius: 2, alignSelf: "center", marginBottom: 12 },
});
