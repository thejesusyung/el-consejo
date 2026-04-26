// Injected at build time via Vite env vars. Populate in .env.production or
// via deployment flags. Falls back to localhost for `npm run dev` against
// a mock or a locally-forwarded API.

export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:3000";
export const WS_URL = import.meta.env.VITE_WS_URL ?? "ws://localhost:3001";
export const ASSETS_URL = import.meta.env.VITE_ASSETS_URL ?? "";
export const AUDIO_OUT_URL = import.meta.env.VITE_AUDIO_OUT_URL ?? "";

export const PERSONAS = [
  { key: "abuela", name: "La Abuela" },
  { key: "mama", name: "La Mamá" },
  { key: "tio", name: "El Tío" },
  { key: "prima", name: "La Prima" },
  { key: "primo", name: "El Primo" },
] as const;

export type PersonaKey = (typeof PERSONAS)[number]["key"];
