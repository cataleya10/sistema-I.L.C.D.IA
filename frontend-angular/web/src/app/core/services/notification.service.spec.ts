import { fakeAsync, TestBed, tick } from '@angular/core/testing';
import { NotificationService } from './notification.service';

describe('NotificationService', () => {
  let service: NotificationService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(NotificationService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should start with null message', () => {
    let msg: string | null = 'initial';
    service.message$.subscribe((m) => (msg = m));
    expect(msg).toBeNull();
  });

  it('should emit message when show is called', () => {
    let msg = null as string | null;
    service.message$.subscribe((m) => (msg = m));

    service.show('Archivo cargado');
    expect(msg as string | null).toBe('Archivo cargado');
  });

  it('should auto-clear after default duration', fakeAsync(() => {
    let msg = null as string | null;
    service.message$.subscribe((m) => (msg = m));

    service.show('Temporal');
    expect(msg as string | null).toBe('Temporal');

    tick(4500);
    expect(msg).toBeNull();
  }));

  it('should auto-clear after custom duration', fakeAsync(() => {
    let msg = null as string | null;
    service.message$.subscribe((m) => (msg = m));

    service.show('Corto', 1000);
    expect(msg as string | null).toBe('Corto');

    tick(1000);
    expect(msg).toBeNull();
  }));

  it('should NOT auto-clear when duration is 0', fakeAsync(() => {
    let msg = null as string | null;
    service.message$.subscribe((m) => (msg = m));

    service.show('Permanente', 0);
    tick(10000);
    expect(msg as string | null).toBe('Permanente');
  }));

  it('should clear message immediately on clear()', () => {
    let msg = null as string | null;
    service.message$.subscribe((m) => (msg = m));

    service.show('Test');
    expect(msg as string | null).toBe('Test');

    service.clear();
    expect(msg).toBeNull();
  });

  it('should reset timer when show is called again', fakeAsync(() => {
    let msg = null as string | null;
    service.message$.subscribe((m) => (msg = m));

    service.show('Primero', 2000);
    tick(1500);
    expect(msg as string | null).toBe('Primero');

    service.show('Segundo', 2000);
    tick(1500);
    expect(msg as string | null).toBe('Segundo');

    tick(500);
    expect(msg).toBeNull();
  }));
});
