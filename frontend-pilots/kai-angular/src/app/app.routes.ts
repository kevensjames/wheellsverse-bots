import { Routes } from '@angular/router';

/**
 * DARK workforce console routes. All views are static, read-only renderings of the
 * generated catalog data. No route performs a network call, activation, or execution.
 */
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'characters' },
  {
    path: 'characters',
    title: 'Characters',
    loadComponent: () => import('./workforce/roster.component').then((m) => m.RosterComponent),
  },
  {
    path: 'org',
    title: 'Org chart',
    loadComponent: () => import('./workforce/org-chart.component').then((m) => m.OrgChartComponent),
  },
  {
    path: 'matrices',
    title: 'Matrices',
    loadComponent: () => import('./workforce/matrices.component').then((m) => m.MatricesComponent),
  },
  {
    path: 'teams',
    title: 'Simulated team',
    loadComponent: () => import('./workforce/team-sim.component').then((m) => m.TeamSimComponent),
  },
  {
    path: 'capabilities',
    title: 'Frontend capabilities',
    loadComponent: () =>
      import('./capability-pilot.component').then((m) => m.CapabilityPilotComponent),
  },
  { path: '**', redirectTo: 'characters' },
];
