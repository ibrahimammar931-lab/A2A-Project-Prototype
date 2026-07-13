import { Component } from '@angular/core';
import { MatSidenavModule } from '@angular/material/sidenav';
import { GlobalControlBarComponent } from '../../components/global-control-bar/global-control-bar.component';
import { PipelineGraphComponent } from '../../components/pipeline-graph/pipeline-graph.component';
import { AgentInspectorComponent } from '../../components/agent-inspector/agent-inspector.component';
import { ApprovalPanelComponent } from '../../components/approval-panel/approval-panel.component';

@Component({
  selector: 'app-control-center',
  standalone: true,
  imports: [MatSidenavModule, GlobalControlBarComponent, PipelineGraphComponent, AgentInspectorComponent, ApprovalPanelComponent],
  template: `
    <app-global-control-bar />
    <mat-drawer-container autosize class="layout">
      <mat-drawer-content>
        <main class="mission">
          <section class="hero">
            <p>Mission Control</p>
            <h1>Python Multi-Agent Workflow</h1>
          </section>
          <app-approval-panel />
          <app-pipeline-graph />
        </main>
      </mat-drawer-content>
      <mat-drawer mode="side" position="end" opened>
        <app-agent-inspector />
      </mat-drawer>
    </mat-drawer-container>
  `,
  styles: [`
    .layout {
      min-height: calc(100vh - 64px);
      background: transparent;
    }

    .mission {
      display: grid;
      gap: 18px;
      padding: 22px;
    }

    .hero {
      display: grid;
      gap: 6px;
    }

    .hero p {
      margin: 0;
      color: #67e8f9;
      font-size: 12px;
      font-weight: 900;
      text-transform: uppercase;
    }

    h1 {
      margin: 0;
      color: #f8fafc;
      font-size: clamp(30px, 4vw, 48px);
      font-weight: 900;
    }

    mat-drawer {
      width: min(420px, 100vw);
      border-left: 1px solid rgba(148, 163, 184, 0.18);
      background: #0b1220;
    }

    @media (max-width: 1180px) {
      mat-drawer {
        width: 360px;
      }
    }
  `]
})
export class ControlCenterComponent {}
