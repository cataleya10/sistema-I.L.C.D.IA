import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';

export const routes: Routes = [
	{
		path: '',
		redirectTo: 'documents/upload',
		pathMatch: 'full'
	},
	{
		path: 'documents',
		loadComponent: () => import('./features/documents/pages/documents-list.page').then(m => m.DocumentsListPage),
		canActivate: [authGuard],
		pathMatch: 'full'
	},
	{
		path: 'login',
		loadComponent: () => import('./features/documents/pages/login.page').then(m => m.LoginPage)
	},
	{
		path: 'documents/upload',
		loadComponent: () => import('./features/documents/pages/documents-upload.page').then(m => m.DocumentsUploadPage)
	},
	{
		path: 'documents/:id',
		loadComponent: () => import('./features/documents/pages/documents-detail.page').then(m => m.DocumentsDetailPage),
		canActivate: [authGuard]
	},
	{
		path: 'documents/:id/results',
		loadComponent: () => import('./features/documents/pages/documents-results.page').then(m => m.DocumentsResultsPage),
		canActivate: [authGuard]
	},
	{
		path: 'system',
		loadComponent: () => import('./features/system/pages/system-metrics.page').then(m => m.SystemMetricsPage),
		canActivate: [authGuard]
	},
	{
		path: '**',
		redirectTo: 'documents/upload'
	}
];
