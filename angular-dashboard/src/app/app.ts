import { Component, OnInit, OnDestroy, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { Subscription } from 'rxjs';
import { AgentListComponent } from './components/agent-list/agent-list';
import { AgentDetailComponent } from './components/agent-detail/agent-detail';
import { LogConsoleComponent } from './components/log-console/log-console';
import { WorkflowLauncherComponent } from './components/workflow-launcher/workflow-launcher';
import { PipelineControlsComponent } from './components/pipeline-controls/pipeline-controls';
import { Agent } from './models/agent.model';
import { LogEntry } from './models/log.model';
import { PipelineService } from './services/pipeline.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    CommonModule,
    MatToolbarModule,
    MatIconModule,
    MatSnackBarModule,
    AgentListComponent,
    AgentDetailComponent,
    LogConsoleComponent,
    WorkflowLauncherComponent,
    PipelineControlsComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnInit, OnDestroy {
  protected readonly title = signal('A2A Dashboard');

  agents: Agent[] = [];
  selectedAgent: Agent | null = null;
  logs: LogEntry[] = [];
  pipelineRunning = false;
  pipelineFinished = false;
  pipelineFailed = false;

  private subs: Subscription[] = [];

  constructor(
    private pipeline: PipelineService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.subs.push(
      this.pipeline.agents$.subscribe((agents) => {
        this.agents = agents;
      }),
    );

    this.subs.push(
      this.pipeline.selectedAgent$.subscribe((agent) => {
        this.selectedAgent = agent;
      }),
    );

    this.subs.push(
      this.pipeline.logs$.subscribe((logs) => {
        this.logs = logs;
      }),
    );

    this.subs.push(
      this.pipeline.pipelineRunning$.subscribe((running) => {
        this.pipelineRunning = running;
      }),
    );

    this.subs.push(
      this.pipeline.pipelineFinished$.subscribe((finished) => {
        this.pipelineFinished = finished;
        if (finished && !this.pipelineFailed) {
          this.snackBar.open('Pipeline completed successfully!', 'Close', {
            duration: 5000,
            panelClass: 'snackbar-success',
          });
        }
      }),
    );

    this.subs.push(
      this.pipeline.pipelineFailed$.subscribe((failed) => {
        this.pipelineFailed = failed;
        if (failed) {
          this.snackBar.open('Pipeline failed! Check the logs for details.', 'Close', {
            duration: 8000,
            panelClass: 'snackbar-error',
          });
        }
      }),
    );
  }

  ngOnDestroy(): void {
    this.subs.forEach((s) => s.unsubscribe());
  }

  onAgentSelected(agent: Agent): void {
    this.pipeline.selectAgent(agent);
  }
}