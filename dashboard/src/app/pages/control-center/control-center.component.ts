import { Component, inject } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatSidenavModule } from '@angular/material/sidenav';
import { GlobalControlBarComponent } from '../../components/global-control-bar/global-control-bar.component';
import { PipelineGraphComponent } from '../../components/pipeline-graph/pipeline-graph.component';
import { AgentInspectorComponent } from '../../components/agent-inspector/agent-inspector.component';
import { ApprovalPanelComponent } from '../../components/approval-panel/approval-panel.component';
import { ModelSelectionPanelComponent } from '../../components/model-selection-panel/model-selection-panel.component';
import { WorkflowStateService } from '../../services/workflow-state.service';

@Component({
  selector: 'app-control-center',
  standalone: true,
  imports: [MatIconModule, MatSidenavModule, GlobalControlBarComponent, PipelineGraphComponent, AgentInspectorComponent, ApprovalPanelComponent, ModelSelectionPanelComponent],
  template: `
    <app-global-control-bar />
    <mat-drawer-container autosize class="layout">
      <mat-drawer-content>
        <main class="mission">
          <section class="hero">
            <p>Mission Control</p>
            <h1>Python Multi-Agent Workflow</h1>
          </section>
          @if (workflow.isManualMode()) {
            <app-approval-panel />
          } @else {
            <section class="auto-notice">
              <div class="auto-badge">
                <mat-icon>auto_mode</mat-icon>
                <span>Automatic Mode Active</span>
              </div>
              <p>The workflow is running automatically. All agents will execute without requiring manual approval.</p>
            </section>
          }
          <app-pipeline-graph />
          <app-model-selection-panel />
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

    .auto-notice {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 18px;
      border: 1px solid rgba(34, 197, 94, 0.26);
      border-radius: 8px;
      background: linear-gradient(135deg, rgba(34, 197, 94, 0.12), rgba(15, 23, 42, 0.84));
    }

    .auto-badge {
      display: flex;
      align-items: center;
      gap: 10px;
      color: #4ade80;
      font-size: 14px;
      font-weight: 900;
      text-transform: uppercase;
    }

    .auto-badge mat-icon {
      font-size: 24px;
      width: 24px;
      height: 24px;
    }

    .auto-notice p {
      margin: 0;
      color: #cbd5e1;
      font-size: 13px;
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
export class ControlCenterComponent {
  readonly workflow = inject(WorkflowStateService);
}