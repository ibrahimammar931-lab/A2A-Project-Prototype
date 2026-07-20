import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, MatIconModule, MatButtonModule],
  template: `
    <nav class="app-nav">
      <a class="brand" routerLink="/">
        <mat-icon>hub</mat-icon>
        <span>Agent Control Center</span>
      </a>
      <div class="links">
        <a mat-button routerLink="/" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: true }">
          <mat-icon>monitor_heart</mat-icon>
          Mission Control
        </a>
        <a mat-button routerLink="/communications" routerLinkActive="active">
          <mat-icon>forum</mat-icon>
          Communications
        </a>
      </div>
    </nav>
    <router-outlet />
  `,
  styles: [`
    :host {
      display: block;
      min-height: 100vh;
    }

    .app-nav {
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 64px;
      padding: 0 22px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.16);
      background: rgba(3, 7, 18, 0.92);
      backdrop-filter: blur(16px);
    }

    .brand {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: #f8fafc;
      font-size: 17px;
      font-weight: 800;
      text-decoration: none;
      white-space: nowrap;
    }

    .brand mat-icon {
      color: #67e8f9;
    }

    .links {
      display: flex;
      align-items: center;
      gap: 4px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    a[mat-button] {
      color: #cbd5e1;
    }

    a[mat-button].active {
      color: #e0f2fe;
      background: rgba(14, 165, 233, 0.14);
    }

    @media (max-width: 720px) {
      .app-nav {
        align-items: flex-start;
        flex-direction: column;
        padding: 12px;
      }
    }
  `]
})
export class AppComponent {}
