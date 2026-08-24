/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  /** "senha" (padrão) ou "entra_id". Precisa acompanhar AUTH_MODE do
   *  backend. Ver src/auth/modo.ts. */
  readonly VITE_AUTH_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
