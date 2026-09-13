import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { WORKFORCE_META } from './workforce/workforce-meta';

/**
 * Shell for the DARK workforce console: brand, the DARK/INERT governance banner,
 * navigation, and the routed views. The shell imports only the tiny WORKFORCE_META
 * (counts + governance strings) so the full 319-character dataset stays in the lazy
 * route chunks. It makes no network call and exposes no action — governed execution
 * is not admitted anywhere in this console.
 */
@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class AppComponent {
  readonly banner = WORKFORCE_META.banner;
  readonly characterCount = WORKFORCE_META.characterCount;
  readonly allInert = WORKFORCE_META.allInert && !WORKFORCE_META.actionsAdmitted;
  readonly notAvailableLabel = WORKFORCE_META.notAvailableLabel;
}
