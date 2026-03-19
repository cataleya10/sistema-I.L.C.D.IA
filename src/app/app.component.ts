import { Component } from '@angular/core';
import { SubirDocumentoLegacyComponent } from './components/subir-documento/subir-documento.component';
import { ResultadoExtraccionComponent } from './resultado-extraccion/resultado-extraccion.component';
import { ResultadoDocumento } from './interfaces/documento-resultado.interface';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [SubirDocumentoLegacyComponent, ResultadoExtraccionComponent],
  templateUrl: './app.component.html'
})
export class AppComponent {
  resultadoExtraccion: ResultadoDocumento | null = null;
}

