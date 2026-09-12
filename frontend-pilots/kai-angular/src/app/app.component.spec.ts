import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';
import { FRONTEND_CAPABILITIES } from './capability-manifest';

/**
 * Unit-test wiring for the pilot. The load-bearing assertion mirrors the
 * backend honesty invariant: the pilot must never render a frontend capability
 * as anything but INERT in Stage 1.
 */
describe('AppComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AppComponent],
    }).compileComponents();
  });

  it('creates the app', () => {
    const fixture = TestBed.createComponent(AppComponent);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('reports every capability as inert (nothing runnable in Stage 1)', () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    expect(app.allInert).toBe(true);
    expect(app.capabilities.length).toBe(FRONTEND_CAPABILITIES.length);
    expect(app.capabilities.every((c) => c.lifecycle === 'INERT')).toBe(true);
  });

  it('renders each capability id in the DOM', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const text: string = fixture.nativeElement.textContent ?? '';
    for (const cap of FRONTEND_CAPABILITIES) {
      expect(text).toContain(cap.capabilityId);
    }
  });
});
