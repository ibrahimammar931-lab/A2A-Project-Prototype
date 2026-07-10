import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatDividerModule } from '@angular/material/divider';
import { Agent, AgentStatus } from '../../models/agent.model';

@Component({
  selector: 'app-agent-detail',
  standalone: true,
  imports: [CommonModule, MatCardModule, MatIconModule, MatDividerModule],
  templateUrl: './agent-detail.html',
  styleUrls: ['./agent-detail.scss'],
})
export class AgentDetailComponent {
  @Input() agent: Agent | null = null;

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
}