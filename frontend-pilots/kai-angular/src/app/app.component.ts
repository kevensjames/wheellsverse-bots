import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { WorkforceService } from './workforce/workforce.service';

/**
 * Shell for the DARK workforce console: brand, the DARK/INERT governance banner,
 * navigation, and the routed views. The shell itself makes no network call and
 * exposes no action — governed execution is not admitted anywhere in this console.
 */
@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class AppComponent {
  readonly banner: string;
  readonly characterCount: number;
  readonly allInert: boolean;
  readonly notAvailableLabel: string;

  constructor(readonly svc: WorkforceService) {
    this.banner = svc.data.governance.banner;
    this.characterCount = svc.data.generatedFrom.characterCount;
    this.allInert = svc.data.generatedFrom.allInert && !svc.actionsAdmitted;
    this.notAvailableLabel = svc.notAvailableLabel;
  }
}
