import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function initials(name: string | undefined | null): string {
  return (name ?? "?")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("") || "?";
}

/** Origine de l'ancien frontend Django (vide = même origine en production). */
export const LEGACY_ORIGIN: string = import.meta.env.VITE_LEGACY_ORIGIN ?? "";
export const legacyUrl = (path: string) => `${LEGACY_ORIGIN}${path}`;
