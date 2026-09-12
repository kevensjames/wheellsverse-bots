import { ApplicationConfig } from '@angular/core';

/**
 * Minimal application config for the pilot. Deliberately no HttpClient and no
 * router providers yet: the pilot renders a static, honest capability view and
 * makes no network calls. Wiring live backend status is a later stage.
 */
export const appConfig: ApplicationConfig = {
  providers: [],
};
