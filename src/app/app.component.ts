import { Component } from '@angular/core';
import { SubirDocumentoComponent } from './components/subir-documento/subir-documento.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [SubirDocumentoComponent],
  templateUrl: './app.component.html'
})
export class AppComponent {}
