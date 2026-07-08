import React from "react";
import { AlmoxarifadoCardsView } from "./AlmoxarifadoPage.jsx";
import "./AlmoxarifadoPage.css";
import "./AlmoxarifadoTheme.css";
import { useAppTheme } from "./theme";

export default function AlmoxarifadoTvPage() {
  const { themeMode, toggleThemeMode, themeLabel } = useAppTheme("dark");
  return <AlmoxarifadoCardsView tv themeMode={themeMode} onToggleTheme={toggleThemeMode} themeLabel={themeLabel} />;
}
