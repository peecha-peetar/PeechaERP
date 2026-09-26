import React, { createContext, useContext, useMemo, useState } from "react";
import { Appearance } from "react-native";
import { ColorPalette, darkColors, lightColors } from "./colors";
import { radius, spacing } from "./spacing";
import { typography } from "./typography";

export type ThemeMode = "light" | "dark";

export interface Theme {
  mode: ThemeMode;
  colors: ColorPalette;
  spacing: typeof spacing;
  radius: typeof radius;
  typography: typeof typography;
}

function buildTheme(mode: ThemeMode): Theme {
  return { mode, colors: mode === "dark" ? darkColors : lightColors, spacing, radius, typography };
}

interface ThemeContextValue {
  theme: Theme;
  setMode: (mode: ThemeMode) => void;
  toggleMode: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

interface ThemeProviderProps {
  children: React.ReactNode;
  /** پیش‌فرض: پیروی از تنظیماتِ سیستم (Appearance) -- طبقِ اصلِ صریحِ
   * «Dark/Light Theme» در فهرستِ نیازمندی‌ها. کاربر می‌تواند بعداً از
   * صفحه‌یِ تنظیمات دستی override کند (setMode/toggleMode). */
  initialMode?: ThemeMode;
}

export function ThemeProvider({ children, initialMode }: ThemeProviderProps) {
  const [mode, setMode] = useState<ThemeMode>(initialMode ?? (Appearance.getColorScheme() === "dark" ? "dark" : "light"));

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: buildTheme(mode),
      setMode,
      toggleMode: () => setMode((m) => (m === "dark" ? "light" : "dark")),
    }),
    [mode],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme باید داخلِ ThemeProvider استفاده شود.");
  return ctx.theme;
}

export function useThemeControls(): Pick<ThemeContextValue, "setMode" | "toggleMode"> {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useThemeControls باید داخلِ ThemeProvider استفاده شود.");
  return { setMode: ctx.setMode, toggleMode: ctx.toggleMode };
}
