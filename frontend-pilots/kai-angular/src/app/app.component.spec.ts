import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { AppComponent } from './app.component';

/**
 * Shell wiring. Load-bearing honesty assertion: the shell reports the console as
 * INERT with no admitted action, and surfaces the governance label.
 */
describe('AppComponent (shell)', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [provideRouter([])],
    }).compileComponents();
  });

  it('creates the shell', () => {
    const fixture = TestBed.createComponent(AppComponent);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('reports DARK/INERT with no admitted action', () => {
    const app = TestBed.createComponent(AppComponent).componentInstance;
    expect(app.allInert).toBe(true);
    expect(app.characterCount).toBe(319);
    expect(app.notAvailableLabel).toContain('NOT AVAILABLE');
  });

  it('renders the governance label and DARK banner', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const text: string = fixture.nativeElement.textContent ?? '';
    expect(text).toContain('DARK · INERT');
    expect(text).toContain('NOT AVAILABLE — GOVERNED EXECUTION NOT ADMITTED');
  });
});
