import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { tap } from 'rxjs/operators';

const API_URL = 'https://localhost:53285';
const TOKEN_KEY = 'ilcdia_token';

interface LoginResponse {
  token: string;
  refresh_token: string;
  username: string;
  role: string;
  expires_at: string;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly authUrl = `${API_URL}/api/auth`;

  constructor(private readonly http: HttpClient) {}

  login(username: string, password: string): Observable<LoginResponse> {
    return this.http
      .post<LoginResponse>(`${this.authUrl}/login`, { username, password })
      .pipe(tap((resp) => localStorage.setItem(TOKEN_KEY, resp.token)));
  }

  getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  }

  isLoggedIn(): boolean {
    return !!this.getToken();
  }

  logout(): void {
    localStorage.removeItem(TOKEN_KEY);
  }
}
