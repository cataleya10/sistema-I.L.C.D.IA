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

function isLocalHost(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';
}

export function getApiBaseUrl(): string {
  const runtimeUrl = normalizeApiUrl(window.__APP_CONFIG__?.apiUrl);
  if (runtimeUrl) {
    return runtimeUrl;
  }

  const fallback = normalizeApiUrl(environment.apiUrl);
  if (fallback) {
    return fallback;
  }

  if (isLocalHost(window.location.hostname)) {
    return 'http://localhost:5000';
  }

  throw new Error('API base URL is not configured. Set window.__APP_CONFIG__.apiUrl before deploying.');
}
