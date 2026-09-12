/**
 * Typed mirror of the KAI frontend capability family. The source of truth is
 * the backend Capability Exchange registry
 * (`backend/app/services/capability_exchange.py`), where these are declared
 * INERT — no adapter bound, cannot execute. This mirror exists so the pilot's
 * own UI can only ever render the honest state: declared, not runnable.
 *
 * `lifecycle` is hard-coded 'INERT' here on purpose. A later, separately-
 * approved stage would fetch live status from the backend; until then the UI
 * must not imply anything is executable.
 */

export type RiskClass = 'READ' | 'ANALYZE' | 'CREATE' | 'CONSEQUENTIAL';
export type ExecutionMode = 'observe' | 'draft' | 'approve_execute';
export type Lifecycle = 'INERT' | 'DISABLED' | 'ENABLED';

export interface CapabilityManifest {
  readonly capabilityId: string;
  readonly riskClass: RiskClass;
  readonly executionMode: ExecutionMode;
  readonly scope: string;
  readonly evidenceTypes: readonly string[];
  readonly approvalPolicy: string;
  readonly lifecycle: Lifecycle;
  readonly description: string;
}

export const FRONTEND_CAPABILITIES: readonly CapabilityManifest[] = [
  {
    capabilityId: 'kai.frontend.scaffold.v1',
    riskClass: 'CREATE',
    executionMode: 'draft',
    scope: 'frontend.scaffold',
    evidenceTypes: ['lockfile_digest', 'tree'],
    approvalPolicy: 'none (draft)',
    lifecycle: 'INERT',
    description: 'ng new inside the sandbox, deny-by-default egress except the registry',
  },
  {
    capabilityId: 'kai.frontend.build.v1',
    riskClass: 'ANALYZE',
    executionMode: 'draft',
    scope: 'frontend.build',
    evidenceTypes: ['build_hash', 'bundle_budget', 'warnings'],
    approvalPolicy: 'none (draft)',
    lifecycle: 'INERT',
    description: 'production build; bundle-size budget is evidence, not prose',
  },
  {
    capabilityId: 'kai.frontend.test.v1',
    riskClass: 'ANALYZE',
    executionMode: 'draft',
    scope: 'frontend.test',
    evidenceTypes: ['unit_results', 'e2e_results', 'a11y', 'lighthouse'],
    approvalPolicy: 'none (draft)',
    lifecycle: 'INERT',
    description: 'unit + e2e (e2e driven by the governed browser runtime) + a11y/Lighthouse',
  },
  {
    capabilityId: 'kai.frontend.preview.v1',
    riskClass: 'READ',
    executionMode: 'observe',
    scope: 'frontend.preview',
    evidenceTypes: ['screenshot', 'console', 'routes'],
    approvalPolicy: 'none (observe)',
    lifecycle: 'INERT',
    description: 'serve locally + drive under host-pin/route/WS/SW/WebRTC egress guards',
  },
  {
    capabilityId: 'kai.frontend.publish.v1',
    riskClass: 'CONSEQUENTIAL',
    executionMode: 'approve_execute',
    scope: 'frontend.publish',
    evidenceTypes: ['destination', 'approval', 'rollback_ref'],
    approvalPolicy: 'named approval + fresh bound single-use approval + evidence',
    lifecycle: 'INERT',
    description: 'deploy ONLY behind named + fresh bound single-use approval; reversible',
  },
];
