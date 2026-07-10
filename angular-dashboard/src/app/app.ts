import { Component, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatIconModule } from '@angular/material/icon';
import { AgentListComponent } from './components/agent-list/agent-list';
import { AgentDetailComponent } from './components/agent-detail/agent-detail';
import { LogConsoleComponent } from './components/log-console/log-console';
import { WorkflowLauncherComponent } from './components/workflow-launcher/workflow-launcher';
import { PipelineControlsComponent } from './components/pipeline-controls/pipeline-controls';
import { Agent, DEFAULT_AGENTS } from './models/agent.model';
import { LogEntry } from './models/log.model';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    CommonModule,
    MatToolbarModule,
    MatIconModule,
    AgentListComponent,
    AgentDetailComponent,
    LogConsoleComponent,
    WorkflowLauncherComponent,
    PipelineControlsComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  protected readonly title = signal('A2A Dashboard');

  agents: Agent[] = [...DEFAULT_AGENTS];
  selectedAgent: Agent | null = null;
  logs: LogEntry[] = [];

  onAgentSelected(agent: Agent): void {
    this.selectedAgent = agent;
  }
}