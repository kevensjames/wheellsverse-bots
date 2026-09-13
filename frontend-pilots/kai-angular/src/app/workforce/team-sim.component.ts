import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { WorkforceService } from './workforce.service';
import { GovernedActionComponent } from './governed-action.component';
import { TeamProposalView } from './workforce.types';

/**
 * Simulated-team interface. It shows team proposals PRE-COMPUTED by the backend
 * catalog (`catalog.propose_team`) — the console carries no planning logic and
 * re-computes nothing. The user browses example missions; every action (assemble /
 * assign / activate / run) is the disabled governed control. A proposal is a
 * description only: it assigns no one and executes nothing.
 */
@Component({
  selector: 'app-team-sim',
  standalone: true,
  imports: [CommonModule, FormsModule, GovernedActionComponent],
  template: `
    <section class="view">
      <header class="view__head">
        <h2>Simulated team (proposal only)</h2>
        <p class="muted">These teams were proposed by KAI's backend catalog and are shown verbatim.
          A proposal is a description of a team KAI <em>could</em> assemble — it assigns no one,
          starts nothing, and every character stays INERT. There is no "assemble" action here.</p>
      </header>

      <label class="pick">Example mission
        <select [(ngModel)]="idx" aria-label="example mission">
          <option *ngFor="let p of proposals; let i = index" [ngValue]="i">{{ p.label }}</option>
        </select>
      </label>

      <article class="proposal" *ngIf="current() as p">
        <div class="proposal__head">
          <div>
            <strong>{{ p.label }}</strong>
            <span class="muted"> · risk {{ p.riskTier }}</span>
          </div>
          <span class="feasible" [class.feasible--no]="!p.feasible">
            {{ p.feasible ? 'feasible proposal' : 'NOT feasible — coverage gap' }}
          </span>
        </div>

        <p class="muted req">requested:
          <span *ngIf="p.requested.divisions.length">divisions [{{ p.requested.divisions.join(', ') }}] </span>
          <span *ngIf="p.requested.frameworks.length">frameworks [{{ p.requested.frameworks.join(', ') }}] </span>
          <span *ngIf="p.requested.consequential.length">consequential [{{ p.requested.consequential.join(', ') }}] </span>
          <span *ngIf="!p.requested.divisions.length && !p.requested.frameworks.length && !p.requested.consequential.length">(none)</span>
        </p>

        <ul class="members">
          <li *ngFor="let m of p.members" class="member">
            <span class="role role--{{ m.role.toLowerCase() }}">{{ roleLabel(m.role) }}</span>
            <span class="who">{{ m.displayName }}</span>
            <span class="why muted">{{ m.rationale }}</span>
          </li>
          <li *ngIf="!p.members.length" class="muted">no team could be staffed</li>
        </ul>

        <div *ngIf="p.coverageGap.hasGap" class="gap">
          coverage gap —
          <span *ngIf="p.coverageGap.missingFrameworks.length">missing frameworks: {{ p.coverageGap.missingFrameworks.join(', ') }} </span>
          <span *ngIf="p.coverageGap.missingDivisions.length">missing divisions: {{ p.coverageGap.missingDivisions.join(', ') }} </span>
          <span *ngIf="p.coverageGap.missingCapabilities.length">missing capabilities: {{ p.coverageGap.missingCapabilities.join(', ') }}</span>
        </div>

        <ul class="notes" *ngIf="p.notes.length">
          <li *ngFor="let n of p.notes" class="muted">{{ n }}</li>
        </ul>

        <dl class="inert">
          <div><dt>proposal only</dt><dd>{{ p.proposalOnly }}</dd></div>
          <div><dt>assigns anyone</dt><dd>{{ p.assignsAnyone }}</dd></div>
          <div><dt>executes anything</dt><dd>{{ p.executesAnything }}</dd></div>
          <div><dt>all members inert</dt><dd>{{ p.allMembersInert }}</dd></div>
        </dl>

        <div class="actions">
          <app-governed-action verb="Assemble team"></app-governed-action>
          <app-governed-action verb="Assign &amp; run"></app-governed-action>
        </div>
      </article>
    </section>
  `,
  styles: [
    `
      .view__head h2 { margin: 0 0 0.25rem; font-size: 1.1rem; }
      .muted { color: var(--muted); }
      .pick { display: inline-flex; flex-direction: column; gap: 0.3rem; color: var(--muted); font-size: 0.85rem; margin: 0.5rem 0 1rem; }
      .pick select { background: var(--panel); color: var(--fg); border: 1px solid var(--line); border-radius: 6px; padding: 0.35rem 0.5rem; font: inherit; min-width: 20rem; }
      .proposal { border: 1px solid var(--line); border-radius: 10px; background: var(--panel); padding: 1rem; max-width: 760px; }
      .proposal__head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
      .feasible { font-size: 0.72rem; color: var(--ok); border: 1px solid var(--ok); border-radius: 999px; padding: 0.1rem 0.5rem; }
      .feasible--no { color: var(--warn); border-color: var(--warn); }
      .req { font-size: 0.8rem; margin: 0.5rem 0; }
      .members { list-style: none; padding: 0; margin: 0.75rem 0; display: flex; flex-direction: column; gap: 0.4rem; }
      .member { display: flex; gap: 0.6rem; align-items: baseline; flex-wrap: wrap; }
      .role { font-size: 0.66rem; letter-spacing: 0.06em; border: 1px solid var(--line); border-radius: 4px; padding: 0.05rem 0.4rem; min-width: 5.5rem; text-align: center; }
      .role--planner { color: var(--accent); border-color: var(--accent); }
      .role--verifier { color: var(--ok); border-color: var(--ok); }
      .role--risk_reviewer { color: var(--warn); border-color: var(--warn); }
      .who { font-size: 0.85rem; }
      .why { font-size: 0.75rem; }
      .gap { color: var(--warn); font-size: 0.8rem; margin: 0.5rem 0; }
      .notes { margin: 0.5rem 0; padding-left: 1rem; font-size: 0.78rem; }
      .inert { display: flex; flex-wrap: wrap; gap: 0.75rem; margin: 0.75rem 0; font-size: 0.75rem; }
      .inert > div { display: flex; gap: 0.35rem; }
      .inert dt { color: var(--muted); }
      .inert dd { margin: 0; }
      .actions { display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid var(--line); }
    `,
  ],
})
export class TeamSimComponent {
  readonly proposals: readonly TeamProposalView[];
  idx = 0;

  constructor(readonly svc: WorkforceService) {
    this.proposals = svc.proposals();
  }

  current(): TeamProposalView | undefined {
    return this.proposals[this.idx];
  }

  roleLabel(role: string): string {
    return role.replace('_', ' ');
  }
}
