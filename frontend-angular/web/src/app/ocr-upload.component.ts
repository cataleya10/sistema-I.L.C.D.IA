import { Component } from '@angular/core';
import { HttpClient } from '@angular/common/http';

@Component({
  selector: 'app-ocr-upload',
  template: `
    <h2>Subir imagen para OCR</h2>
    <input type="file" (change)="onFileSelected($event)" />
    <button (click)="uploadImage()" [disabled]="!selectedFile">Subir</button>
    <div *ngIf="ocrResult">
      <h3>Campos extraídos:</h3>
      <pre>{{ ocrResult.campos | json }}</pre>
      <h3>Tablas extraídas:</h3>
      <pre>{{ ocrResult.tablas | json }}</pre>
      <h3>Tipo de documento:</h3>
      <pre>{{ ocrResult.tipo_documento }}</pre>
      <h3>Confianza:</h3>
      <pre>{{ ocrResult.confianza }}</pre>
      <h3>Advertencias:</h3>
      <pre>{{ ocrResult.advertencias | json }}</pre>
      <div *ngIf="ocrResult && ocrResult.tablas && ocrResult.tablas.length">
        <button (click)="downloadTable('csv')">Descargar tabla CSV</button>
        <button (click)="downloadTable('excel')">Descargar tabla Excel</button>
      </div>
      <div *ngIf="selectedFile && selectedFile.type.startsWith('image/')">
        <div style="position:relative; display:inline-block;">
          <img [src]="imageUrl" alt="Imagen subida" style="max-width:600px; display:block;" />
          <!-- Overlay campos extraídos -->
          <ng-container *ngFor="let campo of ocrResult?.campos">
            <ng-container *ngIf="campo.source && campo.source.bbox">
              <div
                [style.position]="'absolute'"
                [style.left]="campo.source.bbox[0] + 'px'"
                [style.top]="campo.source.bbox[1] + 'px'"
                [style.width]="(campo.source.bbox[2] - campo.source.bbox[0]) + 'px'"
                [style.height]="(campo.source.bbox[3] - campo.source.bbox[1]) + 'px'"
                style="border:2px solid #2196f3; background:rgba(33,150,243,0.15); color:#222; font-size:12px; pointer-events:none; z-index:2;"
                >{{ campo.value }}</div>
            </ng-container>
          </ng-container>
          <!-- Overlay celdas de tablas extraídas -->
          <ng-container *ngFor="let tabla of ocrResult?.tablas">
            <ng-container *ngIf="tabla.celdas && tabla.celdas.length">
              <ng-container *ngFor="let celda of tabla.celdas">
                <ng-container *ngIf="celda.bbox">
                  <div
                    [style.position]="'absolute'"
                    [style.left]="celda.bbox[0] + 'px'"
                    [style.top]="celda.bbox[1] + 'px'"
                    [style.width]="(celda.bbox[2] - celda.bbox[0]) + 'px'"
                    [style.height]="(celda.bbox[3] - celda.bbox[1]) + 'px'"
                    style="border:1px solid #4caf50; background:rgba(76,175,80,0.12); color:#222; font-size:11px; pointer-events:none; z-index:1;"
                    >{{ celda.valor || celda.value }}</div>
                </ng-container>
              </ng-container>
            </ng-container>
          </ng-container>
        </div>
      </div>
    </div>
    <div *ngIf="errorMsg">
      <h3>Error:</h3>
      <pre>{{ errorMsg }}</pre>
    </div>
  `
})
export class OcrUploadComponent {
  selectedFile: File | null = null;
  ocrResult: any = null;
  imageUrl: string | null = null;
  errorMsg: string = '';
  loading: boolean = false;

  constructor(private http: HttpClient) {}

  onFileSelected(event: any) {
    const file = event.target.files[0];
    const allowedTypes = ['image/jpeg', 'image/png', 'application/pdf'];
    if (file && allowedTypes.includes(file.type) && file.size <= 5 * 1024 * 1024) {
      this.selectedFile = file;
      this.errorMsg = '';
      if (file.type.startsWith('image/')) {
        const reader = new FileReader();
        reader.onload = (e: any) => {
          this.imageUrl = e.target.result;
        };
        reader.readAsDataURL(file);
      } else {
        this.imageUrl = null;
      }
    } else {
      this.selectedFile = null;
      this.errorMsg = 'Archivo no permitido o demasiado grande (máx 5MB, solo JPG, PNG, PDF).';
    }
  }

  uploadImage() {
    if (!this.selectedFile) return;
    this.loading = true;
    this.errorMsg = '';
    const formData = new FormData();
    formData.append('file', this.selectedFile);
    this.http.post('/api/ocr/upload', formData).subscribe({
      next: result => {
        this.ocrResult = result;
        this.loading = false;
      },
      error: err => {
        this.errorMsg = err.error || 'Error al procesar la imagen.';
        this.loading = false;
      }
    });
  }
  downloadTable(format: 'csv' | 'excel') {
    if (!this.ocrResult || !this.ocrResult.tablas || !this.ocrResult.tablas.length) return;
    // Asume que la tabla está en ocrResult.tablas[0] y tiene 'columns' y 'rows'
    const tabla = this.ocrResult.tablas[0];
    const columns = tabla.columns || tabla.canonical_columns || [];
    const rows = tabla.rows || tabla.canonical_rows || [];
    if (!columns.length || !rows.length) return;
    const formData = new FormData();
    formData.append('columns', JSON.stringify(columns));
    formData.append('rows', JSON.stringify(rows));
    formData.append('format', format);
    this.http.post(`/api/ocr/export-table`, formData, { responseType: format === 'csv' ? 'text' : 'blob' }).subscribe({
      next: (data: any) => {
        const filename = `tabla.${format === 'csv' ? 'csv' : 'xlsx'}`;
        if (format === 'csv') {
          const blob = new Blob([data], { type: 'text/csv;charset=utf-8;' });
          this.saveFile(blob, filename);
        } else {
          this.saveFile(data, filename);
        }
      },
      error: err => {
        this.errorMsg = err.error || 'Error al exportar la tabla.';
      }
    });
  }

  saveFile(blob: Blob, filename: string) {
    const link = document.createElement('a');
    link.href = window.URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    setTimeout(() => window.URL.revokeObjectURL(link.href), 100);
  }
}
