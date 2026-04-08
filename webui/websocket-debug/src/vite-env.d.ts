/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_NANOBOT_PROXY_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
