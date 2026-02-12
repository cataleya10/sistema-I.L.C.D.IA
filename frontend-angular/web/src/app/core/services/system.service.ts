import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { getApiBaseUrl } from '../config/runtime-config';

export interface SystemInfo {
  service_name: string;
  pipeline_version: string;
  model_version: string;
  timestamp: string;
}

export interface SystemMetrics {
  requests: number;
  errors: number;
  timestamp: string;
}

@Injectable({ providedIn: 'root' })
export class SystemService {
  private readonly baseUrl = `${getApiBaseUrl()}/api/system`;

  constructor(private readonly http: HttpClient) {}

  getInfo() {
    return this.http.get<SystemInfo>(`${this.baseUrl}/info`);
  }

  getMetrics() {
    return this.http.get<SystemMetrics>(`${this.baseUrl}/metrics`);
  }
}
