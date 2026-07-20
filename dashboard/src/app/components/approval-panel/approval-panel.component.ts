import { Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { RouterLink } from '@angular/router';
import { WorkflowStateService } from '../../services/workflow-state.service';

@Component({
  selector: 'app-approval-panel',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, RouterLink],
  template: `
    <section class="approval">
      <div>
        <p class="eyebrow">Manual Execution Mode</p>
        <h2>{{ summary().previousAgent }} completed.</h2>
        <p class="waiting">Next agent: <strong>{{ summary().currentAgent }}</strong> · Waiting for approval</p>
      </div>

      <div class="chain">
        @for (agent of agents(); track agent.name; let index = $index) {
          <span [class.done]="index < currentIndex()" [class.current]="index === currentIndex()">
            <mat-icon>{{ index < currentIndex() ? 'check_circle' : index === currentIndex() ? 'play_arrow' : 'radio_button_unchecked' }}</mat-icon>
            {{ agent.name }}
          </span>
        }
      </div>

      <div class="buttons">
        <button mat-flat-button color="primary" (click)="workflow.runNextAgent()">
          <mat-icon>play_arrow</mat-icon>
          Run Next Agent
        </button>
        <a mat-stroked-button routerLink="/communications">
          <mat-icon>edit</mat-icon>
          Edit Message
        </a>
        <button mat-stroked-button (click)="workflow.rerunCurrentAgent()">
          <mat-icon>replay</mat-icon>
          Re-run Current Agent
        </button>
        <button mat-stroked-button (click)="workflow.skipAgent()">
          <mat-icon>skip_next</mat-icon>
          Skip Agent
        </button>
        <button mat-stroked-button (click)="workflow.cancelWorkflow()">
          <mat-icon>stop</mat-icon>
          Cancel Workflow
        </button>
      </div>
    </section>
  `,
  styles: [`
    .approval {
      display: grid;
      gap: 16px;
      padding: 18px;
      border: 1px solid rgba(251, 191, 36, 0.26);
      border-radius: 8px;
      background: linear-gradient(135deg, rgba(120, 53, 15, 0.38), rgba(15, 23, 42, 0.84));
    }

    .eyebrow {
      margin: 0 0 6px;
      color: #fde68a;
      font-size: 12px;
      font-weight: 900;
      text-transform: uppercase;
    }

    h2 {
      margin: 0;
      color: #f8fafc;
      font-size: 21px;
      font-weight: 800;
    }

    .waiting {
      margin: 6px 0 0;
      color: #cbd5e1;
    }

    .chain, .buttons {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }

    .chain span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 10px;
      border: 1px solid rgba(148, 163, 184, 0.2);
      border-radius: 8px;
      color: #94a3b8;
      background: rgba(15, 23, 42, 0.62);
      font-size: 13px;
      font-weight: 800;
    }

    .chain span.done {
      color: #bbf7d0;
      border-color: rgba(34, 197, 94, 0.34);
    }

    .chain span.current {
      color: #bfdbfe;
      border-color: rgba(59, 130, 246, 0.5);
      background: rgba(37, 99, 235, 0.2);
    }
  `]
})
export class ApprovalPanelComponent {
  readonly workflow = inject(WorkflowStateService);
  readonly summary = this.workflow.summary;
  readonly agents = () => [
    { name: 'Jira' },
    { name: 'Repository' },
    { name: 'Knowledge' },
    { name: 'Planner' },
    { name: 'Developer' },
    { name: 'Reviewer' },
    { name: 'Repository' }
  ];

  currentIndex(): number {
    return this.agents().findIndex((agent) => agent.name === this.summary().currentAgent);
  }
}
