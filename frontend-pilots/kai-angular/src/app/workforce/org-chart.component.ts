import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { WorkforceService } from './workforce.service';

/**
 * Org chart + workplaces. KAI sits at the top; divisions and workplaces are
 * isolation/policy groupings of INERT characters. Pure read-only rendering of the
 * generated org-chart and workplace matrix.
 */
@Component({
  selector: 'app-org-chart',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="view">
      <header class="view__head">
        <h2>Org chart &amp; workplaces</h2>
        <p class="muted">KAI is the sole authority at the top of the org; every division and
          workplace below is a grouping of INERT characters. Any upstream "orchestrator /
          chief-of-staff" role is catalogued as advisory planning only.</p>
      </header>

      <div class="kai-top">KAI — mission · policy · approval · orchestration · completion authority</div>

      <h3 class="sub">Divisions <span class="muted">({{ svc.data.orgChart.length }})</span></h3>
      <div class="grid">
        <article class="card" *ngFor="let g of svc.data.orgChart">
          <div class="card__top">
            <strong>{{ g.division }}</strong>
            <span class="count">{{ g.characterIds.length }}</span>
          </div>
          <ul class="names">
            <li *ngFor="let id of g.characterIds">{{ name(id) }}</li>
          </ul>
        </article>
      </div>

      <h3 class="sub">Workplaces <span class="muted">({{ svc.data.workplaceMatrix.length }} isolation/policy profiles)</span></h3>
      <div class="grid">
        <article class="card card--wp" *ngFor="let w of svc.data.workplaceMatrix">
          <div class="card__top">
            <strong>{{ w.workplace }}</strong>
            <span class="count">{{ w.characterIds.length }}</span>
          </div>
          <p class="muted deny">network denied · browser denied · device denied · external writes denied (default)</p>
        </article>
      </div>
    </section>
  `,
  styles: [
    `
      .view__head h2 { margin: 0 0 0.25rem; font-size: 1.1rem; }
      .muted { color: var(--muted); }
      .kai-top { border: 1px solid var(--accent); border-radius: 8px; background: var(--panel);
        color: var(--accent); padding: 0.6rem 0.9rem; font-size: 0.85rem; margin: 0.75rem 0 1.25rem; text-align: center; }
      .sub { font-size: 0.95rem; margin: 1.25rem 0 0.6rem; }
      .grid { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); }
      .card { border: 1px solid var(--line); border-radius: 10px; background: var(--panel); padding: 0.75rem; }
      .card__top { display: flex; justify-content: space-between; align-items: center; }
      .count { color: var(--muted); font-size: 0.8rem; border: 1px solid var(--line); border-radius: 999px; padding: 0.05rem 0.45rem; }
      .names { list-style: none; margin: 0.5rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.15rem; max-height: 10rem; overflow: auto; }
      .names li { font-size: 0.78rem; color: var(--fg); }
      .card--wp .deny { font-size: 0.72rem; margin: 0.4rem 0 0; }
    `,
  ],
})
export class OrgChartComponent {
  constructor(readonly svc: WorkforceService) {}
  name(id: string): string {
    return this.svc.characterById(id)?.displayName ?? id;
  }
}
