import { Component, Input } from '@angular/core';

/**
 * The ONLY way the console renders an "action". It is always a disabled control
 * carrying the governance label. There is no enabled path, no click handler, and
 * no output — governed execution is not admitted in this dark console. Using this
 * component everywhere an action would appear makes the inert state structural:
 * the UI cannot offer a working button even by mistake.
 */
@Component({
  selector: 'app-governed-action',
  standalone: true,
  template: `
    <span class="governed-action" role="note">
      <button type="button" class="governed-action__btn" disabled aria-disabled="true"
              [attr.title]="label">
        {{ verb }}
      </button>
      <span class="governed-action__label">{{ label }}</span>
    </span>
  `,
  styles: [
    `
      .governed-action {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        flex-wrap: wrap;
      }
      .governed-action__btn {
        font: inherit;
        color: var(--muted);
        background: transparent;
        border: 1px dashed var(--line);
        border-radius: 6px;
        padding: 0.25rem 0.7rem;
        cursor: not-allowed;
        opacity: 0.7;
      }
      .governed-action__label {
        font-size: 0.7rem;
        letter-spacing: 0.04em;
        color: var(--warn);
        border: 1px solid var(--warn);
        border-radius: 999px;
        padding: 0.1rem 0.5rem;
        white-space: nowrap;
      }
    `,
  ],
})
export class GovernedActionComponent {
  /** The action the user might expect (e.g. "Assemble team"). Rendered disabled. */
  @Input() verb = 'Action';
  /** The governance label; defaults to the canonical not-admitted string. */
  @Input() label = 'NOT AVAILABLE — GOVERNED EXECUTION NOT ADMITTED';
}
