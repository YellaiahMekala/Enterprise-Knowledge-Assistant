// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { from, switchMap, tap } from 'rxjs';
import { OidcClient } from './oidc';
import { SessionService } from './session.service';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const session = inject(SessionService);
  const router = inject(Router);
  const oidc = inject(OidcClient);
  return from(session.fresh((token) => oidc.refresh(token))).pipe(
    switchMap(() => {
      const headers = session.authHeaders();
      return next(Object.keys(headers).length ? req.clone({ setHeaders: headers }) : req);
    }),
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
