import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

@Component({
  selector: 'app-pipeline-controls',
  standalone: true,
  imports: [CommonModule, MatButtonModule, MatIconModule, MatTooltipModule],
  templateUrl: './pipeline-controls.html',
  styleUrls: ['./pipeline-controls.scss'],
})
export class PipelineControlsComponent {
  // Pipeline controls are ready for when the backend implements
  // the corresponding endpoints (pause, resume, stop).
  // Currently, the orchestrator only exposes POST /work-on-ticket.
}