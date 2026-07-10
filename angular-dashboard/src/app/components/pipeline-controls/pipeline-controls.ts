import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { OrchestratorService } from '../../services/orchestrator.service';

@Component({
  selector: 'app-pipeline-controls',
  standalone: true,
  imports: [CommonModule, MatButtonModule, MatIconModule, MatSnackBarModule],
  templateUrl: './pipeline-controls.html',
  styleUrls: ['./pipeline-controls.scss'],
})
export class PipelineControlsComponent {
  constructor(
    private orchestrator: OrchestratorService,
    private snackBar: MatSnackBar,
  ) {}

  pause(): void {
    this.orchestrator.pauseWorkflow().subscribe({
      next: () => this.showMessage('Workflow paused'),
      error: (err) => this.showMessage(`Pause failed: ${err.message}`),
    });
  }

  resume(): void {
    this.orchestrator.resumeWorkflow().subscribe({
      next: () => this.showMessage('Workflow resumed'),
      error: (err) => this.showMessage(`Resume failed: ${err.message}`),
    });
  }

  stop(): void {
    this.orchestrator.stopWorkflow().subscribe({
      next: () => this.showMessage('Workflow stopped'),
      error: (err) => this.showMessage(`Stop failed: ${err.message}`),
    });
  }

  private showMessage(msg: string): void {
    this.snackBar.open(msg, 'Close', { duration: 3000 });
  }
}