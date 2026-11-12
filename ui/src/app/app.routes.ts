import { Routes } from '@angular/router';
import { signedInGuard } from './auth';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./login').then((m) => m.Login) },
  { path: 'callback', loadComponent: () => import('./callback').then((m) => m.Callback) },
  {
    path: 'chat',
    canActivate: [signedInGuard],
    loadComponent: () => import('./chat').then((m) => m.Chat),
  },
  {
    path: 'documents',
    canActivate: [signedInGuard],
    loadComponent: () => import('./documents').then((m) => m.Documents),
  },
  {
    path: 'admin',
    canActivate: [signedInGuard],
    loadComponent: () => import('./admin').then((m) => m.Admin),
  },
  { path: '', pathMatch: 'full', redirectTo: 'chat' },
  { path: '**', redirectTo: 'chat' },
];
