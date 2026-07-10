import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatListModule } from '@angular/material/list';
import { MatIconModule } from '@angular/material/icon';
import { Agent, AgentStatus } from '../../models/agent.model';

@Component({
  selector: 'app-agent-list',
  standalone: true,
  imports: [CommonModule, MatListModule, MatIconModule],
  templateUrl: './agent-list.html',
  styleUrls: ['./agent-list.scss'],
})
export class AgentListComponent {
  @Input() agents: Agent[] = [];
  @Input() selectedAgentId: string | null = null;
  @Output() agentSelected = new EventEmitter<Agent>();

  getStatusIcon(status: AgentStatus): string {
    const icons: Record<AgentStatus, string> = {
      waiting: 'hourglass_empty',
      running: 'play_circle',
      completed: 'check_circle',
      failed: 'error',
    };
    return icons[status];
  }

  getStatusColor(status: AgentStatus): string {
    const colors: Record<AgentStatus, string> = {
      waiting: '#9e9e9e',
      running: '#2196f3',
      completed: '#4caf50',
      failed: '#f44336',
    };
    return colors[status];
  }

  selectAgent(agent: Agent): void {
    this.agentSelected.emit(agent);
  }
}