import { Injectable } from '@angular/core';
import { WORKFORCE_DATA } from './workforce-data';
import {
  CharacterView,
  TeamProposalView,
  WorkforceData,
} from './workforce.types';

/**
 * Read-only view service over the static, generated workforce data. It holds the
 * compile-time `WORKFORCE_DATA` and exposes pure reads + client-side filtering.
 *
 * By design it has NO method that activates, assigns, executes, deploys, or calls
 * a model/tool/network — it cannot, because it only ever reads an in-memory
 * literal. KAI's backend catalog remains the sole source of truth; this service
 * re-computes nothing (team proposals are pre-computed by the backend and shown
 * verbatim).
 */
export interface RosterFilter {
  readonly search?: string;
  readonly division?: string;
  readonly sourceKind?: string;
  readonly riskTier?: string;
  readonly framework?: string;
  readonly workplace?: string;
  readonly flaggedOnly?: boolean;
}

@Injectable({ providedIn: 'root' })
export class WorkforceService {
  readonly data: WorkforceData = WORKFORCE_DATA;

  get actionsAdmitted(): boolean {
    return this.data.governance.actionsAdmitted; // always false in this dark console
  }
  get notAvailableLabel(): string {
    return this.data.governance.notAvailableLabel;
  }

  characters(): readonly CharacterView[] {
    return this.data.characters;
  }

  characterById(id: string): CharacterView | undefined {
    return this.data.characters.find((c) => c.id === id);
  }

  divisions(): readonly string[] {
    return this.data.divisions;
  }

  frameworks(): readonly string[] {
    return this.data.frameworks;
  }

  proposals(): readonly TeamProposalView[] {
    return this.data.exampleProposals;
  }

  /** Deterministic client-side filter over the static roster (a pure read). */
  filterRoster(f: RosterFilter): readonly CharacterView[] {
    const q = (f.search ?? '').trim().toLowerCase();
    return this.data.characters.filter((c) => {
      if (f.division && c.division !== f.division) return false;
      if (f.sourceKind && c.sourceKind !== f.sourceKind) return false;
      if (f.riskTier && c.riskTier !== f.riskTier) return false;
      if (f.workplace && c.workplaceProfile !== f.workplace) return false;
      if (f.framework && !c.frameworks.includes(f.framework)) return false;
      if (f.flaggedOnly && !c.flagged) return false;
      if (q && !(`${c.displayName} ${c.id} ${c.roleClass}`.toLowerCase().includes(q))) return false;
      return true;
    });
  }
}
