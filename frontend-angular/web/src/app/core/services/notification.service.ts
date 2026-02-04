import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class NotificationService {
  private readonly messageSubject = new BehaviorSubject<string | null>(null);
  readonly message$ = this.messageSubject.asObservable();
  private timeoutId: ReturnType<typeof setTimeout> | null = null;

  show(message: string, durationMs = 4500): void {
    this.messageSubject.next(message);
    if (this.timeoutId) {
      clearTimeout(this.timeoutId);
    }
    if (durationMs > 0) {
      this.timeoutId = setTimeout(() => this.clear(), durationMs);
    }
  }

  clear(): void {
    if (this.timeoutId) {
      clearTimeout(this.timeoutId);
      this.timeoutId = null;
    }
    this.messageSubject.next(null);
  }
}
