import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Subscription } from 'rxjs';
import { OrchestratorService } from '../../services/orchestrator.service';
import { PipelineService } from '../../services/pipeline.service';
import { WorkflowRequest } from '../../models/workflow-request.model';

@Component({
  selector: 'app-workflow-launcher',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatSnackBarModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './workflow-launcher.html',
  styleUrls: ['./workflow-launcher.scss'],
})
export class WorkflowLauncherComponent implements OnInit, OnDestroy {
  issueKey = '';
  baseBranch = 'main';
  loading = false;

  private subs: Subscription[] = [];

  constructor(
    private orchestrator: OrchestratorService,
    private pipeline: PipelineService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    // Reset loading state when pipeline finishes (via WebSocket event)
    this.subs.push(
      this.pipeline.pipelineRunning$.subscribe((running) => {
        if (!running) {
          this.loading = false;
        }
      }),
    );
  }

  ngOnDestroy(): void {
    this.subs.forEach((s) => s.unsubscribe());
  }

  startWorkflow(): void {
    if (!this.issueKey.trim()) {
      this.snackBar.open('Please enter a valid Issue Key', 'Close', {
        duration: 3000,
        panelClass: 'snackbar-error',
      });
      return;
    }

    this.loading = true;
    const request: WorkflowRequest = {
      issue_key: this.issueKey.trim(),
      base_branch: this.baseBranch.trim() || 'main',
    };

    this.orchestrator.startWorkflow(request).subscribe({
      next: () => {
        // Don't reset loading here — wait for WebSocket pipeline_finished
        // The loading will be reset by the pipelineRunning$ subscription
      },
      error: (err) => {
        this.loading = false;
        this.snackBar.open(
          `Failed to start workflow: ${err.message}`,
          'Close',
          {
            duration: 8000,
            panelClass: 'snackbar-error',
          },
        );
      },
    });
  }
}