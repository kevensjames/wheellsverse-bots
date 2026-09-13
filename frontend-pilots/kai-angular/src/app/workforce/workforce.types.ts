/**
 * Typed view-model for the DARK workforce console. The source of truth is the
 * inert backend `WorkforceCatalog` (`backend/app/services/workforce/catalog.py`);
 * `workforce-data.ts` is generated from it by `ui_export.py`. These types describe
 * static, read-only data only — there is no field here that activates, assigns, or
 * executes anything, and the console makes no network call.
 */

export interface Provenance {
  readonly sourcePath: string | null;
  readonly sourceCommit: string | null;
  readonly sourceHash: string | null;
  readonly license: string;
  readonly reviewedBy: string | null;
}

export interface CharacterView {
  readonly id: string;
  readonly displayName: string;
  readonly codename: string;
  readonly division: string;
  readonly department: string;
  readonly seniority: string;
  readonly roleClass: string;
  readonly sourceKind: 'UPSTREAM' | 'KAI_NATIVE';
  readonly riskTier: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly effectClass: string;
  readonly status: string;
  readonly workplaceProfile: string;
  readonly networkPolicy: string;
  readonly deviceAccess: boolean;
  readonly browserAccess: boolean;
  readonly externalWriteAccess: boolean;
  readonly frameworks: readonly string[];
  readonly declaredCapabilities: readonly string[];
  readonly forbidden: readonly string[];
  readonly flagged: boolean;
  readonly reasonCodes: readonly string[];
  readonly provenance: Provenance;
}

export interface TeamMemberView {
  readonly characterId: string;
  readonly displayName: string;
  readonly role: 'PLANNER' | 'SPECIALIST' | 'RISK_REVIEWER' | 'VERIFIER';
  readonly rationale: string;
}

export interface CoverageGapView {
  readonly missingDivisions: readonly string[];
  readonly missingFrameworks: readonly string[];
  readonly missingCapabilities: readonly string[];
  readonly hasGap: boolean;
}

export interface TeamProposalView {
  readonly label: string;
  readonly missionId: string;
  readonly feasible: boolean;
  readonly riskTier: string;
  readonly requested: {
    readonly divisions: readonly string[];
    readonly frameworks: readonly string[];
    readonly capabilities: readonly string[];
    readonly consequential: readonly string[];
  };
  readonly members: readonly TeamMemberView[];
  readonly coverageGap: CoverageGapView;
  readonly notes: readonly string[];
  /** Inert markers echoed from the authoritative typed proposal. Always false/true. */
  readonly proposalOnly: boolean;
  readonly assignsAnyone: boolean;
  readonly executesAnything: boolean;
  readonly allMembersInert: boolean;
}

export interface DivisionGroup {
  readonly division: string;
  readonly characterIds: readonly string[];
}

export interface WorkplaceGroup {
  readonly workplace: string;
  readonly characterIds: readonly string[];
}

export interface CapabilityGroup {
  readonly capability: string;
  readonly characterIds: readonly string[];
}

export interface WorkforceData {
  readonly generatedFrom: {
    readonly characterCount: number;
    readonly sourceCommit: string;
    readonly allInert: boolean;
  };
  readonly governance: {
    readonly notAvailableLabel: string;
    readonly banner: string;
    readonly actionsAdmitted: boolean;
  };
  readonly summary: Record<string, unknown>;
  readonly divisions: readonly string[];
  readonly orgChart: readonly DivisionGroup[];
  readonly workplaceMatrix: readonly WorkplaceGroup[];
  readonly capabilityMatrix: readonly CapabilityGroup[];
  readonly frameworks: readonly string[];
  readonly characters: readonly CharacterView[];
  readonly exampleProposals: readonly TeamProposalView[];
}
