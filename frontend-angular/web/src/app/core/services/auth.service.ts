import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { environment } from '../../../environments/environment';
import { LoginResponse } from '../../shared/models/document.models';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly baseUrl = `${environment.apiUrl}/api/auth`;
  private readonly tokenKey = 'ilcdia_token';

  constructor(private readonly http: HttpClient) {}

  login(username: string, password: string) {
    return this.http.post<LoginResponse>(`${this.baseUrl}/login`, { username, password });
  }

  setToken(token: string): void {
    localStorage.setItem(this.tokenKey, token);
  }

  getToken(): string | null {
    return localStorage.getItem(this.tokenKey);
  }

  logout(): void {
    localStorage.removeItem(this.tokenKey);
  }
}
