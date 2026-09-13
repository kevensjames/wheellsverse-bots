import { ApplicationConfig } from '@angular/core';
import { provideRouter, withHashLocation } from '@angular/router';
import { routes } from './app.routes';

/**
 * Application config for the DARK workforce console. Provides the router only.
 * Deliberately NO HttpClient and no network providers: the console renders static,
 * generated catalog data and makes no network call. Hash location keeps the static
 * bundle routable without any server rewrite. Wiring a live backend is a later,
 * separately-approved stage.
 */
export const appConfig: ApplicationConfig = {
  providers: [provideRouter(routes, withHashLocation())],
};
