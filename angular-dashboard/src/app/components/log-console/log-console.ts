import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { LogEntry } from '../../models/log.model';

@Component({
  selector: 'app-log-console',
  standalone: true,
  imports: [CommonModule, MatIconModule],
  templateUrl: './log-console.html',
  styleUrls: ['./log-console.scss'],
})
export class LogConsoleComponent {
  @Input() logs: LogEntry[] = [];
}