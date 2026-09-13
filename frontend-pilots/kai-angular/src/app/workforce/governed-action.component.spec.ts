import { TestBed } from '@angular/core/testing';
import { GovernedActionComponent } from './governed-action.component';

/**
 * The governed action control must ALWAYS be disabled and labeled. There is no
 * input, flag, or state that can enable it — the inert state is structural.
 */
describe('GovernedActionComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [GovernedActionComponent] }).compileComponents();
  });

  it('renders a disabled button and the governance label', () => {
    const fixture = TestBed.createComponent(GovernedActionComponent);
    fixture.componentInstance.verb = 'Assemble team';
    fixture.detectChanges();
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button');
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(true);
    const text: string = fixture.nativeElement.textContent ?? '';
    expect(text).toContain('NOT AVAILABLE — GOVERNED EXECUTION NOT ADMITTED');
  });

  it('exposes no output/event emitter (cannot fire an action)', () => {
    const inst: Record<string, unknown> = TestBed.createComponent(GovernedActionComponent)
      .componentInstance as unknown as Record<string, unknown>;
    const hasEmitter = Object.values(inst).some(
      (v) => v != null && typeof (v as { emit?: unknown }).emit === 'function',
    );
    expect(hasEmitter).toBe(false);
  });
});
