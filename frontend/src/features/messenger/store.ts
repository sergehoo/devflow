import { create } from "zustand";

export interface ChatWindow {
  id: number;
  title: string;
  subtitle?: string;
}

interface MessengerUi {
  panelOpen: boolean;
  windows: ChatWindow[];
  setPanelOpen: (open: boolean) => void;
  openWindow: (w: ChatWindow, max: number) => void;
  closeWindow: (id: number) => void;
}

/** État de la bulle flottante (non persisté). */
export const useMessengerUi = create<MessengerUi>((set) => ({
  panelOpen: false,
  windows: [],
  setPanelOpen: (panelOpen) => set({ panelOpen }),
  openWindow: (w, max) => set((s) => ({
    windows: s.windows.some((x) => x.id === w.id) ? s.windows : [...s.windows, w].slice(-max),
  })),
  closeWindow: (id) => set((s) => ({ windows: s.windows.filter((w) => w.id !== id) })),
}));
