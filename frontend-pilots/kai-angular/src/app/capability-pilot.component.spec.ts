import { TestBed } from '@angular/core/testing';
import { CapabilityPilotComponent } from './capability-pilot.component';
import { FRONTEND_CAPABILITIES } from './capability-manifest';

/**
 * The Stage-0 honesty invariant, preserved: the frontend-capability view must
 * never render a capability as anything but INERT.
 */
describe('CapabilityPilotComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [CapabilityPilotComponent] }).compileComponents();
  });

  it('renders every capability as INERT', () => {
    const fixture = TestBed.createComponent(CapabilityPilotComponent);
    const app = fixture.componentInstance;
    expect(app.capabilities.length).toBe(FRONTEND_CAPABILITIES.length);
    expect(app.capabilities.every((c) => c.lifecycle === 'INERT')).toBe(true);
    fixture.detectChanges();
    const text: string = fixture.nativeElement.textContent ?? '';
    for (const cap of FRONTEND_CAPABILITIES) {
      expect(text).toContain(cap.capabilityId);
    }
  });
});
