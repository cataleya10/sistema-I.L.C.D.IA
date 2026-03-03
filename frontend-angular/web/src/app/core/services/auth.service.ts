import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { map } from 'rxjs/operators';
import { getApiBaseUrl } from '../config/runtime-config';
import { LoginResponse } from '../../shared/models/document.models';

export interface AuthSession {
  token: string;
  refreshToken: string;
  username: string;
  role: string;
  expiresAt: string | null;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly baseUrl = `${getApiBaseUrl()}/api/auth`;
  private readonly tokenKey = 'ilcdia_token';
  private readonly refreshTokenKey = 'ilcdia_refresh_token';
  private readonly usernameKey = 'ilcdia_username';
  private readonly roleKey = 'ilcdia_role';
  private readonly tokenExpirySkewSeconds = 30;

  constructor(private readonly http: HttpClient) {}

  login(username: string, password: string) {
    return this.http
      .post<LoginResponse>(`${this.baseUrl}/login`, { username, password })
      .pipe(map((response) => this.normalizeSession(response)));
  }

  loginWithGoogle(idToken: string) {
    return this.http
      .post<LoginResponse>(`${this.baseUrl}/google`, { id_token: idToken })
      .pipe(map((response) => this.normalizeSession(response)));
  }

  register(email: string, password: string) {
    return this.http
      .post<LoginResponse>(`${this.baseUrl}/register`, { email, password })
      .pipe(map((response) => this.normalizeSession(response)));
  }

  refreshToken(refreshToken: string) {
    return this.http
      .post<LoginResponse>(`${this.baseUrl}/refresh`, { refresh_token: refreshToken })
      .pipe(map((response) => this.normalizeSession(response)));
  }

  logoutRemote(refreshToken: string) {
    return this.http.post(`${this.baseUrl}/logout`, { refresh_token: refreshToken });
  }

  setToken(token: string): void {
    localStorage.setItem(this.tokenKey, token);
  }

  setRefreshToken(token: string): void {
    localStorage.setItem(this.refreshTokenKey, token);
  }

  setUser(username: string, role: string): void {
    localStorage.setItem(this.usernameKey, username);
    localStorage.setItem(this.roleKey, role);
  }

  getToken(): string | null {
    const token = localStorage.getItem(this.tokenKey);
    if (!token) {
      return null;
    }

    if (this.isTokenExpired(token)) {
      this.logout();
      return null;
    }

    return token;
  }

  getRefreshToken(): string | null {
    return localStorage.getItem(this.refreshTokenKey);
  }

  getUsername(): string | null {
    return localStorage.getItem(this.usernameKey);
  }

  getRole(): string | null {
    return localStorage.getItem(this.roleKey);
  }

  logout(): void {
    localStorage.removeItem(this.tokenKey);
    localStorage.removeItem(this.refreshTokenKey);
    localStorage.removeItem(this.usernameKey);
    localStorage.removeItem(this.roleKey);
  }

  isAuthenticated(): boolean {
    return this.getToken() !== null;
  }

  private isTokenExpired(token: string): boolean {
    try {
      const parts = token.split('.');
      if (parts.length !== 3) {
        return true;
      }

      const payload = JSON.parse(this.base64UrlDecode(parts[1])) as { exp?: number };
      if (!payload.exp) {
        return true;
      }

      const now = Math.floor(Date.now() / 1000);
      return payload.exp <= now + this.tokenExpirySkewSeconds;
    } catch {
      return true;
    }
  }

  private base64UrlDecode(value: string): string {
    const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
    const padding = normalized.length % 4;
    const padded = padding ? normalized + '='.repeat(4 - padding) : normalized;
    return atob(padded);
  }

  private normalizeSession(response: LoginResponse): AuthSession {
    const refreshToken = response.refresh_token ?? response.refreshToken ?? '';
    const token = response.token?.trim() ?? '';
    const username = response.username?.trim() ?? '';
    const role = response.role?.trim() ?? '';

    if (!token || !refreshToken || !username || !role) {
      throw new Error('Invalid authentication response');
    }

    return {
      token,
      refreshToken,
      username,
      role,
      expiresAt: response.expires_at ?? response.expiresAt ?? null
    };
  }
}
