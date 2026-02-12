import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { getApiBaseUrl } from '../config/runtime-config';
import { LoginResponse } from '../../shared/models/document.models';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly baseUrl = `${getApiBaseUrl()}/api/auth`;
  private readonly tokenKey = 'ilcdia_token';
  private readonly refreshTokenKey = 'ilcdia_refresh_token';
  private readonly usernameKey = 'ilcdia_username';
  private readonly roleKey = 'ilcdia_role';

  constructor(private readonly http: HttpClient) {}

  login(username: string, password: string) {
    return this.http.post<LoginResponse>(`${this.baseUrl}/login`, { username, password });
  }

  refreshToken(refreshToken: string) {
    return this.http.post<LoginResponse>(`${this.baseUrl}/refresh`, { refreshToken });
  }

  logoutRemote(refreshToken: string) {
    return this.http.post(`${this.baseUrl}/logout`, { refreshToken });
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
      return payload.exp <= now;
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
}
