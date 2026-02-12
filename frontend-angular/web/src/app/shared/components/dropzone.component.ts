import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
  selector: 'app-dropzone',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div
      class="dropzone"
      [class.dropzone--dragging]="isDragging"
      (dragover)="onDragOver($event)"
      (dragleave)="onDragLeave($event)"
      (drop)="onDrop($event)"
      (keydown.enter)="openFilePicker(fileInput)"
      (keydown.space)="openFilePicker(fileInput)"
      tabindex="0"
      role="button"
      aria-label="Zona para subir documento"
    >
      <input
        type="file"
        [accept]="accept"
        (change)="onFileInput($event)"
        [attr.multiple]="multiple ? '' : null"
        hidden
        #fileInput
      />
      <div class="dropzone__content">
        <p>{{ label }}</p>
        <button type="button" (click)="openFilePicker(fileInput)">Seleccionar archivo</button>
      </div>
    </div>
  `,
  styles: [
    `
      .dropzone {
        border: 2px dashed #cbd5f5;
        border-radius: 12px;
        padding: 24px;
        text-align: center;
        background: #f8f9ff;
        transition: border-color 0.2s ease, background 0.2s ease;
      }
      .dropzone--dragging {
        border-color: #4f46e5;
        background: #eef2ff;
      }
      .dropzone__content {
        display: grid;
        gap: 12px;
        align-items: center;
        justify-items: center;
        color: #1f2937;
      }
      button {
        padding: 8px 16px;
        border: none;
        border-radius: 999px;
        background: #4f46e5;
        color: #fff;
        cursor: pointer;
      }
    `
  ]
})
export class DropzoneComponent {
  @Input() label = 'Arrastra y suelta tu documento aqui';
  @Input() accept = '.pdf,.png,.jpg,.jpeg';
  @Input() multiple = false;
  @Output() fileDropped = new EventEmitter<File>();

  isDragging = false;

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.isDragging = true;
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.isDragging = false;
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.isDragging = false;
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      this.fileDropped.emit(file);
    }
  }

  onFileInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      this.fileDropped.emit(file);
      input.value = '';
    }
  }

  openFilePicker(fileInput: HTMLInputElement): void {
    fileInput.click();
  }
}

