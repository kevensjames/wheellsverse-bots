import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { CapabilityManifest, FRONTEND_CAPABILITIES, Lifecycle } from './capability-manifest';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class AppComponent {
  readonly capabilities: readonly CapabilityManifest[] = FRONTEND_CAPABILITIES;

  /** Every capability is inert in Stage 1; nothing in this pilot may run one. */
  readonly allInert: boolean = FRONTEND_CAPABILITIES.every((c) => c.lifecycle === 'INERT');

  lifecycleClass(lifecycle: Lifecycle): string {
    return `pill pill--${lifecycle.toLowerCase()}`;
  }

  riskClass(risk: string): string {
    return `tag tag--${risk.toLowerCase()}`;
  }
}
