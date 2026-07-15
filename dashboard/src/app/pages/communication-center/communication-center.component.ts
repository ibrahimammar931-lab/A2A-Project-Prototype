import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { WorkflowStateService } from '../../services/workflow-state.service';
import { JsonViewerComponent } from '../../components/json-viewer/json-viewer.component';
import { MessageEditorComponent } from '../../components/message-editor/message-editor.component';

@Component({
  selector: 'app-communication-center',
  standalone: true,
  imports: [
    FormsModule,
    MatButtonModule,
    MatExpansionModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
    JsonViewerComponent,
    MessageEditorComponent
  ],
  template: `
    <main class="page">
      <header class="title">
        <div>
          <p>Communication Center</p>
          <h1>Agent Conversations</h1>
        </div>
      </header>

      <section class="filters">
        <mat-form-field appearance="outline">
          <mat-label>Sender</mat-label>
          <mat-select [(ngModel)]="sender">
            <mat-option value="">All</mat-option>
            @for (value of senders(); track value) { <mat-option [value]="value">{{ value }}</mat-option> }
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Receiver</mat-label>
          <mat-select [(ngModel)]="receiver">
            <mat-option value="">All</mat-option>
            @for (value of receivers(); track value) { <mat-option [value]="value">{{ value }}</mat-option> }
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Message Type</mat-label>
          <mat-select [(ngModel)]="messageType">
            <mat-option value="">All</mat-option>
            @for (value of types(); track value) { <mat-option [value]="value">{{ value }}</mat-option> }
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Status</mat-label>
          <mat-select [(ngModel)]="status">
            <mat-option value="">All</mat-option>
            @for (value of statuses(); track value) { <mat-option [value]="value">{{ value }}</mat-option> }
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline" class="search">
          <mat-label>Search messages</mat-label>
          <input matInput [(ngModel)]="search" placeholder="planner, payload, file path">
        </mat-form-field>
      </section>

      <section class="content">
        <div class="conversations">
          <mat-accordion multi>
            @for (message of filteredMessages(); track message.id) {
              <mat-expansion-panel (opened)="workflow.selectMessage(message.id)">
                <mat-expansion-panel-header>
                  <mat-panel-title>
                    <span class="route">{{ message.sender }} <mat-icon>south</mat-icon> {{ message.receiver }}</span>
                  </mat-panel-title>
                  <mat-panel-description>
                    {{ message.summary }} · {{ message.status }}
                  </mat-panel-description>
                </mat-expansion-panel-header>

                <div class="message-meta">
                  <span><strong>Time</strong>{{ message.time }}</span>
                  <span><strong>Type</strong>{{ message.type }}</span>
                  <span><strong>Duration</strong>{{ message.duration }}</span>
                  <span><strong>Status</strong>{{ message.status }}</span>
                </div>

                <div class="message-actions">
                  <button mat-stroked-button (click)="workflow.copyJson(message.editedPayload ?? message.payload)">
                    <mat-icon>content_copy</mat-icon>
                    Copy JSON
                  </button>
                  <button mat-stroked-button (click)="workflow.downloadJson(message.id + '.json', message.editedPayload ?? message.payload)">
                    <mat-icon>download</mat-icon>
                    Download JSON
                  </button>
                  <button mat-flat-button color="primary" (click)="workflow.selectMessage(message.id)">
                    <mat-icon>edit</mat-icon>
                    Edit
                  </button>
                </div>

                <app-json-viewer [value]="message.editedPayload ?? message.payload" />
              </mat-expansion-panel>
            }
          </mat-accordion>
        </div>

        <app-message-editor />
      </section>
    </main>
  `,
  styles: [`
    .page {
      display: grid;
      gap: 18px;
      padding: 22px;
    }

    .title p {
      margin: 0 0 6px;
      color: #67e8f9;
      font-size: 12px;
      font-weight: 900;
      text-transform: uppercase;
    }

    h1 {
      margin: 0;
      color: #f8fafc;
      font-size: clamp(28px, 4vw, 42px);
      font-weight: 900;
    }

    .filters {
      display: grid;
      grid-template-columns: repeat(4, minmax(140px, 1fr)) minmax(220px, 1.5fr);
      gap: 12px;
      align-items: start;
    }

    .content {
      display: grid;
      grid-template-columns: minmax(320px, 0.88fr) minmax(420px, 1.12fr);
      gap: 18px;
      align-items: start;
    }

    .content > * {
      min-width: 0;
      overflow: hidden;
    }

    .route {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-weight: 900;
    }

    .message-meta, .message-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }

    .message-meta span {
      min-width: 130px;
      padding: 9px 10px;
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 8px;
      background: rgba(15, 23, 42, 0.6);
      color: #e5eefc;
      font-size: 13px;
    }

    .message-meta strong {
      display: block;
      margin-bottom: 4px;
      color: #94a3b8;
      font-size: 11px;
      text-transform: uppercase;
    }

    @media (max-width: 1100px) {
      .filters, .content {
        grid-template-columns: 1fr;
      }
    }
  `]
})
export class CommunicationCenterComponent {
  readonly workflow = inject(WorkflowStateService);
  readonly senderSignal = signal('');
  readonly receiverSignal = signal('');
  readonly typeSignal = signal('');
  readonly statusSignal = signal('');
  readonly searchSignal = signal('');

  readonly senders = computed(() => unique(this.workflow.messages().map((message) => message.sender)));
  readonly receivers = computed(() => unique(this.workflow.messages().map((message) => message.receiver)));
  readonly types = computed(() => unique(this.workflow.messages().map((message) => message.type)));
  readonly statuses = computed(() => unique(this.workflow.messages().map((message) => message.status)));
  readonly filteredMessages = computed(() => {
    const search = this.searchSignal().trim().toLowerCase();
    return this.workflow.messages().filter((message) => {
      const payloadText = JSON.stringify(message.editedPayload ?? message.payload).toLowerCase();
      return (!this.senderSignal() || message.sender === this.senderSignal())
        && (!this.receiverSignal() || message.receiver === this.receiverSignal())
        && (!this.typeSignal() || message.type === this.typeSignal())
        && (!this.statusSignal() || message.status === this.statusSignal())
        && (!search || `${message.sender} ${message.receiver} ${message.type} ${message.status} ${message.summary} ${payloadText}`.toLowerCase().includes(search));
    });
  });

  get sender(): string { return this.senderSignal(); }
  set sender(value: string) { this.senderSignal.set(value); }
  get receiver(): string { return this.receiverSignal(); }
  set receiver(value: string) { this.receiverSignal.set(value); }
  get messageType(): string { return this.typeSignal(); }
  set messageType(value: string) { this.typeSignal.set(value); }
  get status(): string { return this.statusSignal(); }
  set status(value: string) { this.statusSignal.set(value); }
  get search(): string { return this.searchSignal(); }
  set search(value: string) { this.searchSignal.set(value); }
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values)).sort();
}
