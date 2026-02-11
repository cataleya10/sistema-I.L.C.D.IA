import { CommonModule } from '@angular/common';
import { Component, Input, OnChanges } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';

@Component({
  selector: 'app-document-viewer',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="viewer">
      <div class="viewer-toolbar" *ngIf="fileUrl && !loading && !errorMessage">
        <div class="viewer-kind">{{ isPdf ? 'PDF' : 'Imagen' }}</div>
        <div class="viewer-controls">
          <button type="button" (click)="zoomOut()" [disabled]="zoomValue <= minZoom">-</button>
          <span>{{ zoomPercent }}%</span>
          <button type="button" (click)="zoomIn()" [disabled]="zoomValue >= maxZoom">+</button>
          <button type="button" class="ghost" (click)="resetZoom()" [disabled]="zoomValue === 1">Reset</button>
        </div>
      </div>
      <ng-container *ngIf="loading; else ready">
        <p class="viewer-message">Cargando vista previa...</p>
      </ng-container>
      <ng-template #ready>
        <ng-container *ngIf="errorMessage; else content">
          <p class="viewer-message">{{ errorMessage }}</p>
        </ng-container>
      </ng-template>
      <ng-template #content>
        <ng-container *ngIf="fileUrl; else empty">
          <div class="media">
            <iframe *ngIf="isPdf" [src]="safePdfUrl" title="Documento PDF"></iframe>
            <img *ngIf="!isPdf" [src]="fileUrl" [style.transform]="imageTransform" alt="Documento" />
          </div>
        </ng-container>
      </ng-template>
      <ng-template #empty>
        <p class="viewer-message">Sin documento seleccionado.</p>
      </ng-template>
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
        width: 100%;
        min-width: 0;
      }
      .viewer {
        display: grid;
        align-content: start;
        gap: 10px;
        border-radius: 12px;
        border: 1px solid #e5e7eb;
        background: #fff;
        padding: 14px;
        min-height: 620px;
      }
      .viewer-toolbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
      }
      .viewer-kind {
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.03em;
        text-transform: uppercase;
        color: #334155;
        background: #eef2ff;
        border: 1px solid #c7d2fe;
        border-radius: 999px;
        padding: 5px 10px;
      }
      .viewer-controls {
        display: inline-flex;
        align-items: center;
        gap: 8px;
      }
      .viewer-controls button {
        border: 1px solid #d1d5db;
        background: #fff;
        color: #111827;
        border-radius: 8px;
        min-width: 32px;
        height: 32px;
        padding: 0 10px;
        font-weight: 600;
        cursor: pointer;
      }
      .viewer-controls button.ghost {
        min-width: auto;
      }
      .viewer-controls button:disabled {
        opacity: 0.45;
        cursor: not-allowed;
      }
      .viewer-controls span {
        min-width: 54px;
        text-align: center;
        font-size: 12px;
        font-weight: 600;
        color: #475569;
      }
      .media {
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        background: #f8fafc;
        overflow: hidden;
        overflow: auto;
        display: flex;
        align-items: flex-start;
        justify-content: center;
      }
      iframe,
      img {
        width: 100%;
        height: min(74vh, 860px);
        border: none;
        object-fit: contain;
        background: #f8fafc;
      }
      img {
        width: auto;
        max-width: 100%;
        height: auto;
        min-height: min(74vh, 860px);
        transform-origin: top center;
        transition: transform 120ms ease;
      }
      .viewer-message {
        margin: 0;
        min-height: 160px;
        display: grid;
        place-items: center;
        color: #6b7280;
        font-size: 13px;
        text-align: center;
      }
      @media (max-width: 900px) {
        .viewer {
          min-height: 460px;
        }
        iframe,
        img {
          height: min(56vh, 640px);
          min-height: min(56vh, 640px);
        }
        .viewer-toolbar {
          flex-wrap: wrap;
        }
      }
    `
  ]
})
export class DocumentViewerComponent implements OnChanges {
  @Input() fileUrl: string | null = null;
  @Input() mimeType: string | null = null;
  @Input() loading = false;
  @Input() errorMessage: string | null = null;
  safePdfUrl: SafeResourceUrl | null = null;
  readonly minZoom = 0.5;
  readonly maxZoom = 2.5;
  private readonly zoomStep = 0.1;
  zoomValue = 1;
  private lastFileUrl: string | null = null;

  constructor(private readonly sanitizer: DomSanitizer) {}

  ngOnChanges(): void {
    if (this.fileUrl !== this.lastFileUrl) {
      this.lastFileUrl = this.fileUrl;
      this.zoomValue = 1;
    }
    this.safePdfUrl = this.isPdf && this.fileUrl ? this.sanitizer.bypassSecurityTrustResourceUrl(this.pdfSrc) : null;
  }

  get zoomPercent(): number {
    return Math.round(this.zoomValue * 100);
  }

  get imageTransform(): string {
    return `scale(${this.zoomValue.toFixed(2)})`;
  }

  get pdfSrc(): string {
    if (!this.fileUrl) {
      return '';
    }
    const percent = this.zoomPercent;
    return `${this.fileUrl}#zoom=${percent}`;
  }

  zoomIn(): void {
    this.zoomValue = this.clamp(this.zoomValue + this.zoomStep);
    this.safePdfUrl = this.isPdf && this.fileUrl ? this.sanitizer.bypassSecurityTrustResourceUrl(this.pdfSrc) : null;
  }

  zoomOut(): void {
    this.zoomValue = this.clamp(this.zoomValue - this.zoomStep);
    this.safePdfUrl = this.isPdf && this.fileUrl ? this.sanitizer.bypassSecurityTrustResourceUrl(this.pdfSrc) : null;
  }

  resetZoom(): void {
    this.zoomValue = 1;
    this.safePdfUrl = this.isPdf && this.fileUrl ? this.sanitizer.bypassSecurityTrustResourceUrl(this.pdfSrc) : null;
  }

  private clamp(value: number): number {
    if (value < this.minZoom) {
      return this.minZoom;
    }
    if (value > this.maxZoom) {
      return this.maxZoom;
    }
    return Math.round(value * 100) / 100;
  }

  get isPdf(): boolean {
    return (this.mimeType ?? '').includes('pdf');
  }
}
