import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeMode = "light" | "dark" | "system";

interface UiState {
  theme: ThemeMode;
  sidebarCollapsed: boolean;
  mobileNavOpen: boolean;
  setTheme: (theme: ThemeMode) => void;
  toggleSidebar: () => void;
  setMobileNavOpen: (open: boolean) => void;
}

/** Préférences d'interface uniquement (aucune donnée sensible persistée). */
export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: "system",
      sidebarCollapsed: false,
      mobileNavOpen: false,
      setTheme: (theme) => set({ theme }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setMobileNavOpen: (mobileNavOpen) => set({ mobileNavOpen }),
    }),
    { name: "devflow-ui", partialize: (s) => ({ theme: s.theme, sidebarCollapsed: s.sidebarCollapsed }) },
  ),
);
