import { Component, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatDividerModule } from '@angular/material/divider';
import { WorkflowStateService } from '../../services/workflow-state.service';
import { JsonViewerComponent } from '../json-viewer/json-viewer.component';

@Component({
  selector: 'app-agent-inspector',
  standalone: true,
  imports: [DatePipe, MatExpansionModule, MatIconModule, MatListModule, MatDividerModule, JsonViewerComponent],
  template: `
    @if (agent(); as agent) {
      <aside class="inspector">
        <header>
          <span class="status-pill" [class]="'state-' + agent.status">
            <mat-icon>{{ agent.status === 'running' ? 'play_circle' : agent.status === 'failed' ? 'error' : 'radio_button_checked' }}</mat-icon>
            {{ agent.status }}
          </span>
          <h2>{{ agent.name }}</h2>
          <p>{{ agent.executionState }}</p>
        </header>

        <mat-accordion multi>
          <mat-expansion-panel expanded>
            <mat-expansion-panel-header>
              <mat-panel-title>General</mat-panel-title>
            </mat-expansion-panel-header>
            <dl>
              <dt>Agent Name</dt><dd>{{ agent.name }}</dd>
              <dt>Status</dt><dd>{{ agent.status }}</dd>
              <dt>Start Time</dt><dd>{{ agent.startTime | date:'medium' }}</dd>
              <dt>End Time</dt><dd>{{ agent.endTime ? (agent.endTime | date:'medium') : 'Open' }}</dd>
              <dt>Duration</dt><dd>{{ agent.duration }}</dd>
            </dl>
          </mat-expansion-panel>

          <mat-expansion-panel expanded>
            <mat-expansion-panel-header>
              <mat-panel-title>Activity</mat-panel-title>
            </mat-expansion-panel-header>
            <dl>
              <dt>Current Action</dt><dd>{{ agent.currentAction }}</dd>
              <dt>Execution Count</dt><dd>{{ agent.executionCount }}</dd>
              <dt>Last Execution</dt><dd>{{ agent.lastExecution }}</dd>
            </dl>
          </mat-expansion-panel>

          <mat-expansion-panel>
            <mat-expansion-panel-header>
              <mat-panel-title>Communication</mat-panel-title>
            </mat-expansion-panel-header>
            <dl>
              <dt>Messages Sent</dt><dd>{{ agent.messagesSent }}</dd>
              <dt>Messages Received</dt><dd>{{ agent.messagesReceived }}</dd>
            </dl>
          </mat-expansion-panel>

          <mat-expansion-panel>
            <mat-expansion-panel-header>
              <mat-panel-title>Files</mat-panel-title>
            </mat-expansion-panel-header>
            <h3>Files Read</h3>
            <mat-list dense>
              @for (file of agent.files.read; track file) { <mat-list-item>{{ file }}</mat-list-item> }
            </mat-list>
            <h3>Files Modified</h3>
            <mat-list dense>
              @for (file of agent.files.modified; track file) { <mat-list-item>{{ file }}</mat-list-item> }
            </mat-list>
            <h3>Files Created</h3>
            <mat-list dense>
              @for (file of agent.files.created; track file) { <mat-list-item>{{ file }}</mat-list-item> }
            </mat-list>
          </mat-expansion-panel>

          <mat-expansion-panel expanded>
            <mat-expansion-panel-header>
              <mat-panel-title>Output</mat-panel-title>
            </mat-expansion-panel-header>
            <app-json-viewer [value]="agent.output" />
          </mat-expansion-panel>

          <mat-expansion-panel>
            <mat-expansion-panel-header>
              <mat-panel-title>Errors</mat-panel-title>
            </mat-expansion-panel-header>
            @if (agent.errors.length) {
              @for (error of agent.errors; track error) {
                <p class="error"><mat-icon>error</mat-icon>{{ error }}</p>
              }
            } @else {
              <p class="empty">No errors reported.</p>
            }
          </mat-expansion-panel>
        </mat-accordion>
      </aside>
    }
  `,
  styles: [`
    .inspector {
      width: min(420px, 100%);
      min-height: 100%;
      padding: 18px;
      background: #0b1220;
      color: #e5eefc;
    }

    header {
      display: grid;
      gap: 8px;
      margin-bottom: 18px;
    }

    h2 {
      margin: 0;
      font-size: 26px;
      font-weight: 800;
    }

    header p, .empty {
      margin: 0;
      color: #94a3b8;
    }

    dl {
      display: grid;
      grid-template-columns: minmax(110px, 0.8fr) 1.2fr;
      gap: 10px 14px;
      margin: 0;
    }

    dt {
      color: #94a3b8;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
    }

    dd {
      margin: 0;
      color: #f8fafc;
      overflow-wrap: anywhere;
    }

    h3 {
      margin: 12px 0 4px;
      color: #cbd5e1;
      font-size: 13px;
      font-weight: 800;
      text-transform: uppercase;
    }

    .error {
      display: flex;
      align-items: center;
      gap: 8px;
      color: #fecaca;
      margin: 0;
    }
  `]
})
export class AgentInspectorComponent {
  private readonly workflow = inject(WorkflowStateService);
  readonly agent = this.workflow.selectedAgent;
}
