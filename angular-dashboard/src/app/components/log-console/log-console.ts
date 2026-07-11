import { Component, Input, ViewChild, ElementRef, AfterViewChecked } from '@angular/core';
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
export class LogConsoleComponent implements AfterViewChecked {
  @Input() logs: LogEntry[] = [];

  @ViewChild('logContainer') private logContainer!: ElementRef<HTMLDivElement>;

  private autoScroll = true;

  ngAfterViewChecked(): void {
    this.scrollToBottom();
  }

  onScroll(event: Event): void {
    const el = event.target as HTMLDivElement;
    const threshold = 30;
    this.autoScroll = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
  }

  private scrollToBottom(): void {
    if (!this.autoScroll || !this.logContainer) return;
    try {
      this.logContainer.nativeElement.scrollTop = this.logContainer.nativeElement.scrollHeight;
    } catch {
      // ignore
    }
  }
}