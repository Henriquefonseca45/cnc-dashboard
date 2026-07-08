import { useEffect, useState } from "react";

export const APP_THEME_STORAGE_KEY = "cnc_dashboard_theme";

export function useAppTheme(defaultMode = "dark") {
  const [themeMode, setThemeMode] = useState(() => {
    try {
      return localStorage.getItem(APP_THEME_STORAGE_KEY) || defaultMode;
    } catch {
      return defaultMode;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(APP_THEME_STORAGE_KEY, themeMode);
    } catch {}
  }, [themeMode]);

  function toggleThemeMode() {
    setThemeMode((mode) => (mode === "dark" ? "light" : "dark"));
  }

  return {
    themeMode,
    setThemeMode,
    toggleThemeMode,
    themeLabel: themeMode === "dark" ? "Tema Claro" : "Tema Escuro",
  };
}
