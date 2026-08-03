import { Component, computed, inject, OnInit } from '@angular/core';
import { UpperCasePipe } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { FormsModule } from '@angular/forms';
import { WorkflowStateService } from '../../services/workflow-state.service';

/** Pipeline order for display. */
const AGENT_DISPLAY_ORDER = ['knowledge', 'planner', 'developer', 'reviewer', 'model_selector'] as const;

/** Human-readable labels. */
const AGENT_LABELS: Record<string, string> = {
  knowledge: 'Knowledge',
  planner: 'Planner',
  developer: 'Developer',
  reviewer: 'Reviewer',
  model_selector: 'Model Selector',
};

@Component({
  selector: 'app-model-selection-panel',
  standalone: true,
  imports: [UpperCasePipe, MatCardModule, MatSelectModule, MatButtonModule, MatIconModule, MatSlideToggleModule, MatSnackBarModule, FormsModule],
  template: `
    <mat-card class="model-panel">
      <mat-card-header>
        <mat-card-title>
          <mat-icon>psychology</mat-icon>
          Agent Model Selection
        </mat-card-title>
        <mat-card-subtitle>
          @if (workflow.autoModelSelection()) {
            🤖 Auto mode — the LLM-based Model Selector picks models per workflow run.
          } @else {
            Choose which model each agent uses. Changes persist across workflow runs.
          }
        </mat-card-subtitle>
      </mat-card-header>
      <mat-card-content class="panel-grid">
        @for (agentKey of agentKeys; track agentKey) {
          <div class="agent-row">
            <label class="agent-label">{{ agentLabels[agentKey] }}</label>
            <mat-form-field appearance="outline" class="model-select">
              <mat-select
                [(ngModel)]="selections[agentKey]"
                placeholder="Auto-selected"
                [disabled]="workflow.autoModelSelection()"
              >
                <mat-option [value]="''">
                  Auto-selected
                </mat-option>
                @for (model of groupedModels(); track model.id) {
                  <mat-option [value]="model.id">
                    {{ model.provider | uppercase }} — {{ model.label }}
                  </mat-option>
                }
              </mat-select>
            </mat-form-field>
          </div>
        }
      </mat-card-content>
      <mat-card-actions align="end">
        <button mat-flat-button color="primary" (click)="save()" [disabled]="workflow.autoModelSelection()">
          <mat-icon>save</mat-icon>
          Save Selection
        </button>
      </mat-card-actions>
    </mat-card>
  `,
  styles: [`
    .model-panel {
      border: 1px solid rgba(148, 163, 184, 0.18);
      background: #0b1220;
    }
    mat-card-title {
      display: flex;
      align-items: center;
      gap: 8px;
      color: #f8fafc;
    }
    mat-card-subtitle {
      color: #94a3b8;
    }
    .panel-grid {
      display: grid;
      gap: 12px;
      padding-top: 12px;
    }
    .agent-row {
      display: grid;
      grid-template-columns: 120px 1fr;
      align-items: center;
      gap: 12px;
    }
    .agent-label {
      color: #cbd5e1;
      font-size: 14px;
      font-weight: 600;
      text-align: right;
    }
    .model-select {
      width: 100%;
    }
    @media (max-width: 600px) {
      .agent-row {
        grid-template-columns: 1fr;
      }
      .agent-label {
        text-align: left;
      }
    }
  `],
})
export class ModelSelectionPanelComponent implements OnInit {
  readonly workflow = inject(WorkflowStateService);
  private readonly snackBar = inject(MatSnackBar);

  readonly agentKeys = [...AGENT_DISPLAY_ORDER];
  readonly agentLabels = AGENT_LABELS;

  /** Local model to avoid mutating the signal directly until save. */
  selections: Record<string, string> = {};

  /** Models from signal, reshaped to provider-prefixed labels. */
  readonly groupedModels = () => this.workflow.availableModels();

  ngOnInit(): void {
    this.workflow.loadAvailableModels();
    this.workflow.loadModelSelection();
    // Initialise local selections from the current signal value — the
    // HTTP call inside loadModelSelection() sets the signal when it
    // completes, so on any subsequent init (e.g. route re-activation)
    // the signal already carries the latest persisted state.
    const current = this.workflow.modelSelection();
    for (const key of AGENT_DISPLAY_ORDER) {
      this.selections[key] = current[key] ?? '';
    }
  }

  save(): void {
    const payload: Partial<Record<string, string>> = {};
    for (const key of AGENT_DISPLAY_ORDER) {
      const val = this.selections[key];
      payload[key] = val && val.trim() ? val.trim() : '';
    }
    this.workflow.saveModelSelection(payload);
    this.snackBar.open('Model selection saved.', 'Dismiss', { duration: 3000 });
  }
}
