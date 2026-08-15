import { Component, computed, inject, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTooltipModule } from '@angular/material/tooltip';
import { WorkflowStateService } from '../../services/workflow-state.service';
import { WorkflowStatus, WorkspaceMode } from '../../models/workflow.models';

@Component({
  selector: 'app-global-control-bar',
  standalone: true,
  imports: [FormsModule, MatButtonModule, MatButtonToggleModule, MatFormFieldModule, MatIconModule, MatInputModule, MatProgressBarModule, MatSlideToggleModule, MatTooltipModule],
  template: `
    <section class="control-bar">
      <div class="summary-line">
        <span class="status-pill" [class]="statusClass()">
          <mat-icon>{{ statusIcon() }}</mat-icon>
          {{ label(summary().status) }}
        </span>
        <div class="metric"><span>Ticket</span><strong>{{ summary().ticket }}</strong></div>
        <div class="metric"><span>Branch</span><strong>{{ summary().branch }}</strong></div>
        <div class="metric"><span>Repository</span><strong>{{ summary().repository }}</strong></div>
        <div class="metric"><span>Running Agent</span><strong>{{ summary().runningAgent }}</strong></div>
        <div class="metric wide"><span>Current Action</span><strong>{{ summary().currentAction }}</strong></div>
        <div class="metric"><span>Total Time</span><strong>{{ summary().totalExecutionTime }}</strong></div>
        <div class="metric mode-indicator" [class.manual]="workflow.isManualMode()" [class.automatic]="workflow.isAutomaticMode()">
          <span>Mode</span>
          <strong>{{ workflow.isManualMode() ? '🔧 Manual' : '🤖 Automatic' }}</strong>
        </div>
      </div>

      <div class="start-inputs">
        <div class="workspace-toggle">
          <span>Workspace</span>
          <mat-button-toggle-group [(ngModel)]="workspaceMode" hideSingleSelectionIndicator="true">
            <mat-button-toggle value="git" matTooltip="Clone or update a GitHub repository and let the workflow create/apply to branches">
              <mat-icon>cloud_sync</mat-icon>
              Git Repo
            </mat-button-toggle>
            <mat-button-toggle value="local" matTooltip="Use the currently checked-out branch in a local git folder">
              <mat-icon>folder_open</mat-icon>
              Local Folder
            </mat-button-toggle>
          </mat-button-toggle-group>
        </div>
        <mat-form-field appearance="outline">
          <mat-label>Ticket</mat-label>
          <input matInput [(ngModel)]="workflowTicket" placeholder="A2A-184">
        </mat-form-field>
        @if (workspaceMode === 'git') {
          <mat-form-field appearance="outline">
            <mat-label>Base Branch</mat-label>
            <input matInput [(ngModel)]="workflowBranch" placeholder="main">
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Existing Branch</mat-label>
            <input matInput [(ngModel)]="workflowExistingBranch" placeholder="feature/my-branch">
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Repo URL</mat-label>
            <input matInput [(ngModel)]="workflowRepoUrl" placeholder="https://github.com/owner/repo">
          </mat-form-field>
        } @else {
          <mat-form-field appearance="outline" class="local-path">
            <mat-label>Local Folder Path</mat-label>
            <input matInput [(ngModel)]="workflowLocalPath" placeholder="C:\\Users\\you\\project">
          </mat-form-field>
        }
      </div>

      <div class="actions">
        <mat-button-toggle-group [value]="workflow.currentMode()" (change)="onModeToggle($event)" hideSingleSelectionIndicator="true">
          <mat-button-toggle value="manual" matTooltip="Each agent requires approval before running">
            <mat-icon>touch_app</mat-icon>
            Manual
          </mat-button-toggle>
          <mat-button-toggle value="automatic" matTooltip="Workflow runs automatically without requiring approval">
            <mat-icon>auto_mode</mat-icon>
            Automatic
          </mat-button-toggle>
        </mat-button-toggle-group>

        <mat-slide-toggle
          [ngModel]="workflow.autoModelSelection()"
          (ngModelChange)="onAutoModelToggle($event)"
          color="accent"
          matTooltip="Let the LLM-based Model Selector choose which model each agent uses (Auto) or pick them yourself (Manual)">
          <span class="auto-model-label">
            <mat-icon>psychology</mat-icon>
            {{ workflow.autoModelSelection() ? 'Auto Models' : 'Manual Models' }}
          </span>
        </mat-slide-toggle>

        <mat-slide-toggle [(ngModel)]="workflowOpenPr" color="primary" [disabled]="workspaceMode === 'local'" matTooltip="Open a pull request after applying changes">
          Open PR
        </mat-slide-toggle>

        <button mat-flat-button color="primary" (click)="startWorkflow()">
          <mat-icon>play_arrow</mat-icon>
          Start Workflow
        </button>
        <button mat-stroked-button (click)="workflow.stopWorkflow()">
          <mat-icon>stop</mat-icon>
          Stop
        </button>
        <button mat-stroked-button (click)="restartWorkflow()">
          <mat-icon>restart_alt</mat-icon>
          Restart
        </button>
        <button mat-stroked-button (click)="workflow.exportExecutionLog()" matTooltip="Export the current execution snapshot as JSON">
          <mat-icon>download</mat-icon>
          Export Log
        </button>
      </div>

      <mat-progress-bar mode="determinate" [value]="summary().progress"></mat-progress-bar>
    </section>
  `,
  styles: [`
    .control-bar {
      display: grid;
      gap: 14px;
      padding: 16px 22px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.16);
      background: rgba(8, 13, 24, 0.94);
      backdrop-filter: blur(16px);
      box-shadow: 0 16px 40px rgba(0, 0, 0, 0.22);
    }

    .summary-line, .actions {
      display: flex;
      align-items: stretch;
      gap: 10px;
      flex-wrap: wrap;
    }

    .start-inputs {
      display: grid;
      grid-template-columns: minmax(220px, 320px) minmax(180px, 260px) minmax(180px, 260px) minmax(180px, 260px) minmax(180px, 260px);
      gap: 10px;
      align-items: start;
    }

    .workspace-toggle {
      display: grid;
      gap: 4px;
      min-width: 220px;
    }

    .workspace-toggle > span {
      color: #94a3b8;
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
    }

    .local-path {
      grid-column: span 3;
    }

    .metric {
      min-width: 132px;
      padding: 9px 11px;
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 8px;
      background: rgba(15, 23, 42, 0.62);
    }

    .metric.wide {
      flex: 1 1 260px;
    }

    .metric span {
      display: block;
      color: #94a3b8;
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
    }

    .metric strong {
      display: block;
      overflow: hidden;
      color: #f8fafc;
      font-size: 13px;
      font-weight: 700;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .status-pill {
      min-width: 178px;
      justify-content: center;
      border: 1px solid currentColor;
    }

    .mode-indicator.manual {
      border-color: rgba(251, 191, 36, 0.4);
      background: rgba(251, 191, 36, 0.08);
    }

    .mode-indicator.automatic {
      border-color: rgba(34, 197, 94, 0.4);
      background: rgba(34, 197, 94, 0.08);
    }

    button mat-icon {
      margin-right: 6px;
    }

    .auto-model-label {
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }

    .auto-model-label mat-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
    }

    @media (max-width: 720px) {
      .control-bar {
        padding: 12px;
      }

      .metric, .status-pill {
        flex: 1 1 100%;
      }

      .start-inputs {
        grid-template-columns: 1fr;
      }
    }
  `]
})
export class GlobalControlBarComponent implements OnInit {
  readonly workflow = inject(WorkflowStateService);
  readonly summary = this.workflow.summary;
  readonly statusClass = computed(() => `state-${this.summary().status}`);
  readonly statusIcon = computed(() => statusIcon(this.summary().status));
  workflowTicket = localStorage.getItem('workflowTicket') ?? '';
  workflowBranch = localStorage.getItem('workflowBranch') ?? '';
  workflowExistingBranch = localStorage.getItem('workflowExistingBranch') ?? '';
  workflowRepoUrl = localStorage.getItem('workflowRepoUrl') ?? '';
  workflowLocalPath = localStorage.getItem('workflowLocalPath') ?? '';
  workspaceMode: WorkspaceMode = (localStorage.getItem('workspaceMode') as WorkspaceMode | null) ?? 'git';
  workflowOpenPr = localStorage.getItem('workflowOpenPr') !== 'false';
  label(value: string): string {
    return value.split('-').map((part) => part[0].toUpperCase() + part.slice(1)).join(' ');
  }

  ngOnInit(): void {
    this.workflow.fetchAutoModelSelection();
  }

  onModeToggle(event: any): void {
    const newMode = event.value;
    this.workflow.setMode(newMode);
  }

  onAutoModelToggle(enabled: boolean): void {
    this.workflow.setAutoModelSelection(enabled);
  }

  startWorkflow(): void {
    const ticket = this.workflowTicket.trim();
    const branch = this.workflowBranch.trim() || 'main';
    const existingBranch = this.workflowExistingBranch.trim();
    const openPr = this.workspaceMode === 'git' && this.workflowOpenPr;
    const repoUrl = this.workflowRepoUrl.trim();
    const localPath = this.workflowLocalPath.trim();
    localStorage.setItem('workflowTicket', ticket);
    localStorage.setItem('workflowBranch', branch);
    localStorage.setItem('workflowExistingBranch', existingBranch);
    localStorage.setItem('workflowOpenPr', String(openPr));
    localStorage.setItem('workflowRepoUrl', repoUrl);
    localStorage.setItem('workflowLocalPath', localPath);
    localStorage.setItem('workspaceMode', this.workspaceMode);
    this.workflow.startWorkflow(ticket, branch, existingBranch, openPr, repoUrl, this.workspaceMode, localPath);
  }

  restartWorkflow(): void {
    const openPr = this.workspaceMode === 'git' && this.workflowOpenPr;
    this.workflow.restartWorkflow(
      this.workflowExistingBranch.trim(),
      openPr,
      this.workflowRepoUrl.trim(),
      this.workspaceMode,
      this.workflowLocalPath.trim()
    );
  }
}

function statusIcon(status: WorkflowStatus): string {
  return {
    running: 'play_circle',
    waiting: 'schedule',
    paused: 'pause_circle',
    failed: 'error',
    completed: 'check_circle',
    'requires-revision': 'edit_note'
  }[status];
}
