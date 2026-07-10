import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { OrchestratorService } from '../../services/orchestrator.service';
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
export class WorkflowLauncherComponent {
  issueKey = '';
  baseBranch = 'main';
  loading = false;

  constructor(
    private orchestrator: OrchestratorService,
    private snackBar: MatSnackBar,
  ) {}

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
        this.loading = false;
        this.snackBar.open('Workflow started successfully!', 'Close', {
          duration: 5000,
          panelClass: 'snackbar-success',
        });
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