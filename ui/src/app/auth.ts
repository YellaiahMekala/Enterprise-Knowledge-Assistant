import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { tap } from 'rxjs';
import { SessionService } from './session.service';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const session = inject(SessionService);
  const router = inject(Router);
  const key = session.apiKey();
  const authed = key ? req.clone({ setHeaders: { 'X-API-Key': key } }) : req;
  return next(authed).pipe(
    tap({
      error: (e) => {
        if (e.status === 401) {
          session.signOut();
          router.navigate(['/login']);
        }
      },
    }),
  );
};

export const signedInGuard: CanActivateFn = () => {
  const session = inject(SessionService);
  return session.signedIn() || inject(Router).createUrlTree(['/login']);
};
