import { TestBed } from '@angular/core/testing';
import { WorkforceService } from './workforce.service';

/**
 * Data-honesty invariants for the DARK console (runnable under ng test in the
 * governed sandbox). The generated data must describe 319 INERT characters, admit
 * no action, and every example proposal must assign/execute nothing.
 */
describe('WorkforceService (data honesty)', () => {
  let svc: WorkforceService;
  beforeEach(() => {
    TestBed.configureTestingModule({});
    svc = TestBed.inject(WorkforceService);
  });

  it('holds exactly 319 characters, all INERT', () => {
    expect(svc.characters().length).toBe(319);
    expect(svc.characters().every((c) => c.status === 'INERT')).toBe(true);
    expect(svc.data.generatedFrom.allInert).toBe(true);
  });

  it('admits no action and carries the canonical label', () => {
    expect(svc.actionsAdmitted).toBe(false);
    expect(svc.notAvailableLabel).toBe('NOT AVAILABLE — GOVERNED EXECUTION NOT ADMITTED');
  });

  it('every example proposal assigns and executes nothing', () => {
    for (const p of svc.proposals()) {
      expect(p.assignsAnyone).toBe(false);
      expect(p.executesAnything).toBe(false);
      expect(p.proposalOnly).toBe(true);
      expect(p.allMembersInert).toBe(true);
    }
  });

  it('provenance is honest (KAI_NATIVE carries none; nothing human-approved)', () => {
    for (const c of svc.characters()) {
      expect(c.provenance.reviewedBy).toBeNull();
      if (c.sourceKind === 'KAI_NATIVE') {
        expect(c.provenance.sourceHash).toBeNull();
      } else {
        expect(typeof c.provenance.sourceHash).toBe('string');
      }
    }
  });

  it('filterRoster is a pure read that never grows the set', () => {
    const all = svc.characters().length;
    expect(svc.filterRoster({ division: 'NoSuchDivision' }).length).toBe(0);
    expect(svc.filterRoster({}).length).toBe(all);
  });
});
