import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatStepperModule } from '@angular/material/stepper';
import { MatListModule } from '@angular/material/list';
import { WorkflowStateService } from '../../services/workflow-state.service';
import { JsonViewerComponent } from '../json-viewer/json-viewer.component';
import { StructuredJsonEditorComponent } from '../structured-json-editor/structured-json-editor.component';

@Component({
  selector: 'app-message-editor',
  standalone: true,
  imports: [FormsModule, MatButtonModule, MatIconModule, MatFormFieldModule, MatInputModule, MatStepperModule, MatListModule, JsonViewerComponent, StructuredJsonEditorComponent],
  template: `
    @if (message(); as message) {
      <section class="editor">
        <header>
          <div>
            <p class="eyebrow">Message Editor</p>
            <h2>{{ message.sender }} → {{ message.receiver }}</h2>
          </div>
          <span class="status-pill" [class]="'state-' + message.status">{{ message.status }}</span>
        </header>

        <mat-horizontal-stepper linear="false" [selectedIndex]="stepIndex()">
          <mat-step label="Original Message"></mat-step>
          <mat-step label="Edited Message"></mat-step>
          <mat-step label="Pending Approval"></mat-step>
          <mat-step label="Sent"></mat-step>
        </mat-horizontal-stepper>

        <div class="compare">
          <div>
            <h3>Original Message</h3>
            <app-json-viewer [value]="message.payload" />
          </div>
          <div>
            <h3>Edited Message</h3>
            <app-structured-json-editor
              [value]="draftObject()"
              (valueChange)="onDraftChanged($event)"
            />
          </div>
        </div>

        <mat-form-field appearance="outline">
          <mat-label>User change summary</mat-label>
          <input matInput [(ngModel)]="changeSummary" placeholder="Added task statistics service to likely files">
        </mat-form-field>

        <div class="buttons">
          <button mat-flat-button color="primary" (click)="save(message.id)">
            <mat-icon>save</mat-icon>
            Save
          </button>
          <button mat-stroked-button (click)="send(message.id)">
            <mat-icon>send</mat-icon>
            Send
          </button>
          <button mat-stroked-button (click)="reset(message.payload)">
            <mat-icon>restart_alt</mat-icon>
            Reset Draft
          </button>
        </div>

        <section class="history">
          <h3>User Changes</h3>
          @if (message.userChanges.length) {
            <mat-list>
              @for (change of message.userChanges; track change.time) {
                <mat-list-item>
                  <span matListItemTitle>{{ change.description }}</span>
                  <span matListItemLine>{{ change.author }} · {{ change.time }}</span>
                </mat-list-item>
              }
            </mat-list>
          } @else {
            <p>No user edits recorded yet.</p>
          }
        </section>
      </section>
    }
  `,
  styles: [`
    .editor {
      display: grid;
      gap: 16px;
      padding: 18px;
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 8px;
      background: rgba(15, 23, 42, 0.68);
      min-width: 0;
    }

    header, .buttons {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }

    .eyebrow {
      margin: 0 0 4px;
      color: #67e8f9;
      font-size: 12px;
      font-weight: 900;
      text-transform: uppercase;
    }

    h2, h3 {
      margin: 0;
      color: #f8fafc;
    }

    h2 {
      font-size: 22px;
      font-weight: 800;
    }

    h3 {
      margin-bottom: 10px;
      font-size: 14px;
      font-weight: 900;
      text-transform: uppercase;
    }

    .compare {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }

    .compare > div {
      min-width: 0;
      overflow: hidden;
    }

    mat-form-field {
      width: 100%;
    }

    textarea {
      font-family: 'Roboto Mono', monospace;
      font-size: 12px;
      line-height: 1.5;
      max-height: 500px;
      overflow-y: auto;
    }

    .history p {
      margin: 0;
      color: #94a3b8;
    }

    @media (max-width: 920px) {
      .compare {
        grid-template-columns: 1fr;
      }
    }
  `]
})
export class MessageEditorComponent {
  private readonly workflow = inject(WorkflowStateService);
  readonly message = this.workflow.selectedMessage;
  readonly draftSignal = signal<unknown>(null);
  readonly changeSignal = signal('Edited message payload');
  readonly stepIndex = computed(() => {
    const status = this.message()?.status;
    if (status === 'sent' || status === 'delivered') {
      return 3;
    }
    if (status === 'pending-approval') {
      return 2;
    }
    if (this.message()?.editedPayload) {
      return 1;
    }
    return 0;
  });

  readonly draftObject = computed(() => {
    const message = this.message();
    const current = this.draftSignal();
    if (current !== null) {
      return current;
    }
    if (message) {
      return message.editedPayload ?? message.payload;
    }
    return null;
  });

  get changeSummary(): string {
    return this.changeSignal();
  }

  set changeSummary(value: string) {
    this.changeSignal.set(value);
  }

  onDraftChanged(edited: unknown): void {
    this.draftSignal.set(edited);
  }

  save(messageId: string): void {
    const edited = this.draftSignal();
    if (edited !== null) {
      this.workflow.saveEditedMessage(messageId, edited, this.changeSummary || 'Edited message payload');
    }
  }

  send(messageId: string): void {
    this.workflow.sendEditedMessage(messageId);
  }

  reset(payload: unknown): void {
    this.draftSignal.set(structuredClone(payload));
  }
}
