import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { environment } from '../../../environments/environment';
import { LoginResponse } from '../../shared/models/document.models';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly baseUrl = `${environment.apiUrl}/api/auth`;
  private readonly tokenKey = 'ilcdia_token';
  private readonly refreshTokenKey = 'ilcdia_refresh_token';

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

  getToken(): string | null {
    return localStorage.getItem(this.tokenKey);
  }

  getRefreshToken(): string | null {
    return localStorage.getItem(this.refreshTokenKey);
  }

  logout(): void {
    localStorage.removeItem(this.tokenKey);
    localStorage.removeItem(this.refreshTokenKey);
  }
}
