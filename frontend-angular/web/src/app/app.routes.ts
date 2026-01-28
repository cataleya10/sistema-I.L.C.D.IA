import { Routes } from '@angular/router';
import { DocumentsListPage } from './features/documents/pages/documents-list.page';
import { DocumentsUploadPage } from './features/documents/pages/documents-upload.page';
import { DocumentsDetailPage } from './features/documents/pages/documents-detail.page';
import { LoginPage } from './features/documents/pages/login.page';
import { authGuard } from './core/guards/auth.guard';

export const routes: Routes = [
	{
		path: '',
		redirectTo: 'documents',
		pathMatch: 'full'
	},
	{
		path: 'documents',
		component: DocumentsListPage,
		canActivate: [authGuard],
		pathMatch: 'full'
	},
	{
		path: 'login',
		component: LoginPage
	},
	{
		path: 'documents/upload',
		component: DocumentsUploadPage,
		canActivate: [authGuard]
	},
	{
		path: 'documents/:id',
		component: DocumentsDetailPage,
		canActivate: [authGuard]
	},
	{
		path: '**',
		redirectTo: 'documents'
	}
];
