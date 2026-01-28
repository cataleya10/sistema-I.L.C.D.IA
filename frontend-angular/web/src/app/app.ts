import { Component } from '@angular/core';
import { AppShellComponent } from './core/layout/app-shell.component';

@Component({
  selector: 'app-root',
  imports: [AppShellComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App {
}
