import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { WorkforceService } from './workforce.service';

/**
 * Matrices view: capability matrix (declared capability → characters), framework
 * coverage, and risk / source tallies. All derived from the static generated data.
 */
@Component({
  selector: 'app-matrices',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="view">
      <header class="view__head">
        <h2>Capability, framework &amp; risk matrices</h2>
        <p class="muted">Declared capabilities are advisory/draft and uniform across the normalized
          roster (by design); framework expertise is a derived, read-time classification and does
          not authorize installing any framework.</p>
      </header>

      <h3 class="sub">Risk &amp; source</h3>
      <div class="tallies">
        <div class="tally"><span class="k">characters</span><span class="v">{{ svc.characters().length }}</span></div>
        <div class="tally"><span class="k">KAI_NATIVE</span><span class="v">{{ count('sourceKind','KAI_NATIVE') }}</span></div>
        <div class="tally"><span class="k">UPSTREAM</span><span class="v">{{ count('sourceKind','UPSTREAM') }}</span></div>
        <div class="tally"><span class="k">risk LOW</span><span class="v">{{ count('riskTier','LOW') }}</span></div>
        <div class="tally"><span class="k">risk MEDIUM</span><span class="v">{{ count('riskTier','MEDIUM') }}</span></div>
        <div class="tally"><span class="k">flagged</span><span class="v">{{ flaggedCount }}</span></div>
        <div class="tally"><span class="k">all INERT</span><span class="v">{{ svc.data.generatedFrom.allInert ? 'yes' : 'NO' }}</span></div>
      </div>

      <h3 class="sub">Capability matrix</h3>
      <table class="tbl">
        <thead><tr><th>Declared capability</th><th>Characters</th></tr></thead>
        <tbody>
          <tr *ngFor="let c of svc.data.capabilityMatrix">
            <td><code>{{ c.capability }}</code></td>
            <td class="muted">{{ c.characterIds.length }}</td>
          </tr>
        </tbody>
      </table>

      <h3 class="sub">Framework coverage <span class="muted">({{ svc.frameworks().length }})</span></h3>
      <table class="tbl">
        <thead><tr><th>Framework (declared expertise)</th><th>Characters</th></tr></thead>
        <tbody>
          <tr *ngFor="let f of svc.frameworks()">
            <td>{{ f }}</td>
            <td class="muted">{{ frameworkCount(f) }}</td>
          </tr>
          <tr *ngIf="!svc.frameworks().length"><td colspan="2" class="muted">none derived</td></tr>
        </tbody>
      </table>
    </section>
  `,
  styles: [
    `
      .view__head h2 { margin: 0 0 0.25rem; font-size: 1.1rem; }
      .muted { color: var(--muted); }
      .sub { font-size: 0.95rem; margin: 1.25rem 0 0.6rem; }
      .tallies { display: flex; flex-wrap: wrap; gap: 0.6rem; }
      .tally { border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 0.5rem 0.75rem; display: flex; flex-direction: column; min-width: 6rem; }
      .tally .k { color: var(--muted); font-size: 0.72rem; }
      .tally .v { font-size: 1.1rem; }
      .tbl { width: 100%; border-collapse: collapse; font-size: 0.85rem; max-width: 640px; }
      .tbl th { text-align: left; color: var(--muted); font-weight: 600; padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--line); }
      .tbl td { padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--line); }
    `,
  ],
})
export class MatricesComponent {
  readonly flaggedCount: number;

  constructor(readonly svc: WorkforceService) {
    this.flaggedCount = svc.characters().filter((c) => c.flagged).length;
  }

  count(field: 'sourceKind' | 'riskTier', value: string): number {
    return this.svc.characters().filter((c) => c[field] === value).length;
  }

  frameworkCount(f: string): number {
    return this.svc.characters().filter((c) => c.frameworks.includes(f)).length;
  }
}
