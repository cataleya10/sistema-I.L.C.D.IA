import { Component } from '@angular/core';
import { SubirDocumentoLegacyComponent } from './components/subir-documento/subir-documento.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [SubirDocumentoLegacyComponent],
  templateUrl: './app.component.html'
})
export class AppComponent {}
