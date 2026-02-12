import { environment } from '../../../environments/environment';

type RuntimeConfig = {
  apiUrl?: string;
};

declare global {
  interface Window {
    __APP_CONFIG__?: RuntimeConfig;
  }
}

function normalizeApiUrl(value: string | undefined | null): string | null {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }

  return trimmed.replace(/\/+$/, '');
}

export function getApiBaseUrl(): string {
  const runtimeUrl = normalizeApiUrl(window.__APP_CONFIG__?.apiUrl);
  if (runtimeUrl) {
    return runtimeUrl;
  }

  const fallback = normalizeApiUrl(environment.apiUrl);
  return fallback ?? 'http://localhost:5000';
}

