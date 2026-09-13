import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { WorkforceService } from './workforce.service';
import { GovernedActionComponent } from './governed-action.component';
import { CharacterView } from './workforce.types';

/**
 * Roster view: all 319 INERT characters, filterable by division / source / risk /
 * framework / workplace / flagged, with a free-text search. Selecting a character
 * opens an inline detail panel (provenance + risk + quarantine + capabilities).
 * Read-only: the only "action" is the disabled governed control.
 */
@Component({
  selector: 'app-roster',
  standalone: true,
  imports: [CommonModule, FormsModule, GovernedActionComponent],
  template: `
    <section class="view">
      <header class="view__head">
        <h2>Characters <span class="count">{{ rows.length }} / {{ total }}</span></h2>
        <p class="muted">Every character is INERT — declared, never runnable. Admission,
          assignment, and execution are separate, owner-authorized governed steps.</p>
      </header>

      <div class="filters">
        <input type="search" placeholder="search name / id / role" [(ngModel)]="search"
               (ngModelChange)="apply()" aria-label="search characters" />
        <select [(ngModel)]="division" (ngModelChange)="apply()" aria-label="division">
          <option value="">all divisions</option>
          <option *ngFor="let d of svc.divisions()" [value]="d">{{ d }}</option>
        </select>
        <select [(ngModel)]="sourceKind" (ngModelChange)="apply()" aria-label="source">
          <option value="">any source</option>
          <option value="KAI_NATIVE">KAI_NATIVE</option>
          <option value="UPSTREAM">UPSTREAM</option>
        </select>
        <select [(ngModel)]="riskTier" (ngModelChange)="apply()" aria-label="risk">
          <option value="">any risk</option>
          <option value="LOW">LOW</option>
          <option value="MEDIUM">MEDIUM</option>
          <option value="HIGH">HIGH</option>
          <option value="CRITICAL">CRITICAL</option>
        </select>
        <select [(ngModel)]="framework" (ngModelChange)="apply()" aria-label="framework">
          <option value="">any framework</option>
          <option *ngFor="let f of svc.frameworks()" [value]="f">{{ f }}</option>
        </select>
        <label class="chk"><input type="checkbox" [(ngModel)]="flaggedOnly"
               (ngModelChange)="apply()" /> flagged only</label>
      </div>

      <table class="tbl">
        <thead>
          <tr><th>Name</th><th>Division</th><th>Role</th><th>Source</th><th>Risk</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>
          <ng-container *ngFor="let c of rows">
            <tr class="tbl__row" (click)="toggle(c.id)" [class.tbl__row--open]="selectedId === c.id">
              <td>{{ c.displayName }} <span *ngIf="c.flagged" class="flag" title="quarantine flag">⚑</span></td>
              <td>{{ c.division }}</td>
              <td class="muted">{{ c.roleClass }}</td>
              <td><span class="src" [class.src--native]="c.sourceKind === 'KAI_NATIVE'">{{ c.sourceKind }}</span></td>
              <td><span [class]="riskClass(c.riskTier)">{{ c.riskTier }}</span></td>
              <td><span class="pill pill--inert">{{ c.status }}</span></td>
              <td class="muted">{{ selectedId === c.id ? '▾' : '▸' }}</td>
            </tr>
            <tr *ngIf="selectedId === c.id" class="detail">
              <td colspan="7">
                <div class="detail__grid">
                  <div>
                    <h4>Identity</h4>
                    <dl>
                      <div><dt>id</dt><dd><code>{{ c.id }}</code></dd></div>
                      <div><dt>codename</dt><dd><code>{{ c.codename }}</code></dd></div>
                      <div><dt>department</dt><dd>{{ c.department }}</dd></div>
                      <div><dt>seniority</dt><dd>{{ c.seniority }}</dd></div>
                      <div><dt>workplace</dt><dd>{{ c.workplaceProfile }}</dd></div>
                    </dl>
                  </div>
                  <div>
                    <h4>Provenance</h4>
                    <dl>
                      <div><dt>license</dt><dd>{{ c.provenance.license }}</dd></div>
                      <div><dt>source</dt><dd><code>{{ c.provenance.sourcePath || '— (KAI-native)' }}</code></dd></div>
                      <div><dt>commit</dt><dd><code>{{ shortHash(c.provenance.sourceCommit) }}</code></dd></div>
                      <div><dt>hash</dt><dd><code>{{ shortHash(c.provenance.sourceHash) }}</code></dd></div>
                      <div><dt>reviewed by</dt><dd>{{ c.provenance.reviewedBy || 'none (not human-approved)' }}</dd></div>
                    </dl>
                  </div>
                  <div>
                    <h4>Risk &amp; workplace</h4>
                    <dl>
                      <div><dt>risk</dt><dd><span [class]="riskClass(c.riskTier)">{{ c.riskTier }}</span></dd></div>
                      <div><dt>effect</dt><dd>{{ c.effectClass }}</dd></div>
                      <div><dt>network</dt><dd>{{ c.networkPolicy }}</dd></div>
                      <div><dt>device</dt><dd>{{ c.deviceAccess ? 'on' : 'denied' }}</dd></div>
                      <div><dt>browser</dt><dd>{{ c.browserAccess ? 'on' : 'denied' }}</dd></div>
                      <div><dt>ext. write</dt><dd>{{ c.externalWriteAccess ? 'on' : 'denied' }}</dd></div>
                    </dl>
                  </div>
                  <div *ngIf="c.flagged">
                    <h4>Quarantine review</h4>
                    <p class="muted">Upstream source was flagged in intake; findings are preserved as
                      inert evidence (never imported into this manifest).</p>
                    <ul class="chips"><li *ngFor="let r of c.reasonCodes">{{ r }}</li></ul>
                  </div>
                  <div class="detail__wide">
                    <h4>Frameworks (declared expertise)</h4>
                    <ul class="chips"><li *ngFor="let f of c.frameworks">{{ f }}</li>
                      <li *ngIf="!c.frameworks.length" class="muted">none derived</li></ul>
                    <h4>Capabilities</h4>
                    <p class="muted">declared: {{ c.declaredCapabilities.join(', ') }}</p>
                    <p class="muted">forbidden: {{ c.forbidden.join(' · ') }}</p>
                    <div class="detail__act"><app-governed-action verb="Admit / assign"></app-governed-action></div>
                  </div>
                </div>
              </td>
            </tr>
          </ng-container>
          <tr *ngIf="!rows.length"><td colspan="7" class="muted empty">No characters match these filters.</td></tr>
        </tbody>
      </table>
    </section>
  `,
  styles: [
    `
      .view__head h2 { margin: 0 0 0.25rem; font-size: 1.1rem; }
      .count { color: var(--muted); font-size: 0.85rem; font-weight: 400; }
      .muted { color: var(--muted); }
      .filters { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 1rem 0; }
      .filters input, .filters select {
        background: var(--panel); color: var(--fg); border: 1px solid var(--line);
        border-radius: 6px; padding: 0.3rem 0.5rem; font: inherit;
      }
      .chk { display: inline-flex; align-items: center; gap: 0.3rem; color: var(--muted); font-size: 0.85rem; }
      .tbl { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
      .tbl th { text-align: left; color: var(--muted); font-weight: 600; padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--line); }
      .tbl__row { cursor: pointer; border-bottom: 1px solid var(--line); }
      .tbl__row:hover { background: var(--panel); }
      .tbl__row--open { background: var(--panel); }
      .tbl td { padding: 0.4rem 0.5rem; vertical-align: top; }
      .flag { color: var(--warn); }
      .src { font-size: 0.68rem; border: 1px solid var(--line); border-radius: 999px; padding: 0.05rem 0.4rem; }
      .src--native { color: var(--accent); border-color: var(--accent); }
      .detail { background: var(--bg); }
      .detail__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; padding: 0.75rem 0.5rem 1rem; }
      .detail__wide { grid-column: 1 / -1; }
      .detail__act { margin-top: 0.75rem; }
      .detail h4 { margin: 0 0 0.4rem; font-size: 0.8rem; letter-spacing: 0.04em; color: var(--accent); }
      .detail dl { margin: 0; }
      .detail dl > div { display: flex; gap: 0.5rem; padding: 0.1rem 0; font-size: 0.8rem; }
      .detail dt { color: var(--muted); min-width: 5.5rem; }
      .detail dd { margin: 0; }
      .chips { list-style: none; display: flex; flex-wrap: wrap; gap: 0.3rem; padding: 0; margin: 0 0 0.5rem; }
      .chips li { font-size: 0.7rem; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 0.05rem 0.45rem; }
      .pill { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; padding: 0.1rem 0.45rem; border-radius: 999px; border: 1px solid var(--line); }
      .pill--inert { color: var(--muted); }
      .risk { font-size: 0.7rem; padding: 0.05rem 0.45rem; border-radius: 4px; border: 1px solid var(--line); }
      .risk--low { color: var(--ok); }
      .risk--medium { color: var(--warn); border-color: var(--warn); }
      .risk--high, .risk--critical { color: #ff7b72; border-color: #ff7b72; }
      .empty { text-align: center; padding: 1.5rem; }
    `,
  ],
})
export class RosterComponent {
  readonly total: number;
  search = '';
  division = '';
  sourceKind = '';
  riskTier = '';
  framework = '';
  flaggedOnly = false;
  selectedId: string | null = null;
  rows: readonly CharacterView[];

  constructor(readonly svc: WorkforceService) {
    this.total = svc.characters().length;
    this.rows = svc.characters();
  }

  apply(): void {
    this.rows = this.svc.filterRoster({
      search: this.search, division: this.division, sourceKind: this.sourceKind,
      riskTier: this.riskTier, framework: this.framework, flaggedOnly: this.flaggedOnly,
    });
  }

  toggle(id: string): void {
    this.selectedId = this.selectedId === id ? null : id;
  }

  riskClass(risk: string): string {
    return `risk risk--${risk.toLowerCase()}`;
  }

  shortHash(v: string | null): string {
    return v ? (v.length > 12 ? v.slice(0, 12) + '…' : v) : '—';
  }
}
