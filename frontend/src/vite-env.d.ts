/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_WS_URL?: string;
  readonly VITE_ASSETS_URL?: string;
  readonly VITE_AUDIO_OUT_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
