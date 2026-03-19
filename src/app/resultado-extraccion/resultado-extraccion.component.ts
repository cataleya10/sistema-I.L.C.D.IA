import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ResultadoDocumento } from '../interfaces/documento-resultado.interface';

@Component({
  selector: 'app-resultado-extraccion',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './resultado-extraccion.component.html',
  styleUrls: ['./resultado-extraccion.component.css']
})
export class ResultadoExtraccionComponent {
  @Input() resultado: ResultadoDocumento | null = null;
}

