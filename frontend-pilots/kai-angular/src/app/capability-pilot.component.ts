import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { CapabilityManifest, FRONTEND_CAPABILITIES, Lifecycle } from './capability-manifest';

/**
 * The Stage-0 dark frontend-capability view, now a route within the workforce
 * console. Source of truth: `backend/app/services/capability_exchange.py`
 * (catalog-only, execution_supported=False). Every capability renders INERT.
 */
@Component({
  selector: 'app-capability-pilot',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="view">
      <header class="view__head">
        <h2>Governed frontend capabilities</h2>
        <p class="muted">Declared in the inert Capability Exchange registry. No adapter is bound,
          nothing is installed, nothing is deployed. Execution is a later, separately-approved step.</p>
      </header>

      <div class="grid">
        <article class="card" *ngFor="let cap of capabilities">
          <div class="card__top">
            <code class="card__id">{{ cap.capabilityId }}</code>
            <span [class]="lifecycleClass(cap.lifecycle)">{{ cap.lifecycle }}</span>
          </div>
          <p class="card__desc">{{ cap.description }}</p>
          <dl class="meta">
            <div class="meta__row"><dt>Risk</dt><dd><span [class]="riskClass(cap.riskClass)">{{ cap.riskClass }}</span></dd></div>
            <div class="meta__row"><dt>Mode</dt><dd>{{ cap.executionMode }}</dd></div>
            <div class="meta__row"><dt>Scope</dt><dd><code>{{ cap.scope }}</code></dd></div>
            <div class="meta__row"><dt>Approval</dt><dd>{{ cap.approvalPolicy }}</dd></div>
          </dl>
          <ul class="evidence" aria-label="Evidence types">
            <li *ngFor="let e of cap.evidenceTypes">{{ e }}</li>
          </ul>
        </article>
      </div>
    </section>
  `,
  styles: [
    `
      .view__head h2 { margin: 0 0 0.25rem; font-size: 1.1rem; }
      .muted { color: var(--muted); }
      .grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); margin-top: 1rem; }
      .card { border: 1px solid var(--line); border-radius: 10px; background: var(--panel); padding: 1rem; }
      .card__top { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
      .card__id { font-size: 0.82rem; }
      .card__desc { color: var(--muted); font-size: 0.86rem; margin: 0.6rem 0 0.8rem; }
      .meta { margin: 0; }
      .meta__row { display: flex; gap: 0.5rem; padding: 0.15rem 0; font-size: 0.82rem; }
      .meta dt { color: var(--muted); min-width: 4.5rem; }
      .meta dd { margin: 0; }
      .evidence { list-style: none; display: flex; flex-wrap: wrap; gap: 0.35rem; padding: 0.75rem 0 0; margin: 0; }
      .evidence li { font-size: 0.72rem; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 0.1rem 0.55rem; }
      .pill { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; padding: 0.15rem 0.5rem; border-radius: 999px; border: 1px solid var(--line); }
      .pill--inert { color: var(--muted); }
      .pill--disabled { color: var(--warn); }
      .pill--enabled { color: var(--ok); }
      .tag { font-size: 0.72rem; padding: 0.05rem 0.4rem; border-radius: 4px; border: 1px solid var(--line); }
      .tag--consequential { color: var(--warn); border-color: var(--warn); }
    `,
  ],
})
export class CapabilityPilotComponent {
  readonly capabilities: readonly CapabilityManifest[] = FRONTEND_CAPABILITIES;

  lifecycleClass(lifecycle: Lifecycle): string {
    return `pill pill--${lifecycle.toLowerCase()}`;
  }
  riskClass(risk: string): string {
    return `tag tag--${risk.toLowerCase()}`;
  }
}
