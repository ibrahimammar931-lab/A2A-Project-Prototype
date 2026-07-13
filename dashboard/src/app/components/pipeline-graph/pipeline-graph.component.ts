import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild, effect, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import cytoscape, { Core, ElementDefinition } from 'cytoscape';
import { WorkflowStateService } from '../../services/workflow-state.service';

@Component({
  selector: 'app-pipeline-graph',
  standalone: true,
  imports: [MatButtonModule, MatIconModule],
  template: `
    <section class="graph-shell">
      <div class="graph-toolbar">
        <div>
          <h2>Workflow Pipeline</h2>
          <p>Zoom, pan, and select any agent to inspect execution state.</p>
        </div>
        <div class="tools">
          <button mat-icon-button aria-label="Zoom in" (click)="zoom(1.16)">
            <mat-icon>zoom_in</mat-icon>
          </button>
          <button mat-icon-button aria-label="Zoom out" (click)="zoom(0.86)">
            <mat-icon>zoom_out</mat-icon>
          </button>
          <button mat-icon-button aria-label="Fit graph to screen" (click)="fit()">
            <mat-icon>fit_screen</mat-icon>
          </button>
        </div>
      </div>
      <div class="legend">
        <span><i class="waiting"></i>Waiting</span>
        <span><i class="running"></i>Running</span>
        <span><i class="success"></i>Success</span>
        <span><i class="revision"></i>Requires Revision</span>
        <span><i class="failed"></i>Failed</span>
      </div>
      <div #graph class="graph"></div>
    </section>
  `,
  styles: [`
    .graph-shell {
      display: grid;
      min-height: 560px;
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 8px;
      background: #08111f;
      overflow: hidden;
    }

    .graph-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 76px;
      padding: 14px 16px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.14);
      background: rgba(15, 23, 42, 0.82);
    }

    .legend {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      min-height: 42px;
      padding: 8px 16px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.14);
      background: rgba(2, 6, 23, 0.62);
      color: #cbd5e1;
      font-size: 12px;
      font-weight: 800;
    }

    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 7px;
    }

    .legend i {
      width: 11px;
      height: 11px;
      border-radius: 50%;
      border: 1px solid rgba(255, 255, 255, 0.46);
    }

    .legend .waiting { background: #64748b; }
    .legend .running { background: #2563eb; }
    .legend .success { background: #16a34a; }
    .legend .revision { background: #f97316; }
    .legend .failed { background: #dc2626; }

    h2 {
      margin: 0;
      color: #f8fafc;
      font-size: 20px;
      font-weight: 800;
    }

    p {
      margin: 4px 0 0;
      color: #94a3b8;
      font-size: 13px;
    }

    .tools {
      display: flex;
      gap: 4px;
    }

    .graph {
      width: 100%;
      min-height: 500px;
    }
  `]
})
export class PipelineGraphComponent implements AfterViewInit, OnDestroy {
  @ViewChild('graph', { static: true }) private graphElement!: ElementRef<HTMLElement>;

  private readonly workflow = inject(WorkflowStateService);
  private cy?: Core;
  private resizeObserver?: ResizeObserver;

  constructor() {
    effect(() => {
      const agents = this.workflow.agents();
      const activePath = this.workflow.activePath();
      const selectedAgentId = this.workflow.selectedAgentId();
      if (!this.cy) {
        return;
      }

      this.cy.batch(() => {
        this.cy?.elements().removeClass('active-path active-node selected-node');
        for (const agent of agents) {
          const node = this.cy?.getElementById(agent.id);
          node?.data({
            label: agent.name,
            detail: `${this.prettyStatus(agent.status)} · ${agent.executionState}`,
            status: agent.status
          });
          node?.classes(`agent status-${agent.status}`);
        }

        for (let index = 0; index < activePath.length; index += 1) {
          this.cy?.getElementById(activePath[index]).addClass(index === activePath.length - 1 ? 'active-node' : 'active-path');
          if (index < activePath.length - 1) {
            this.cy?.getElementById(`${activePath[index]}-${activePath[index + 1]}`).addClass('active-path');
          }
        }
        if (selectedAgentId) {
          this.cy?.getElementById(selectedAgentId).addClass('selected-node');
        }
      });
    });
  }

  ngAfterViewInit(): void {
    this.cy = cytoscape({
      container: this.graphElement.nativeElement,
      elements: this.elements(),
      pixelRatio: 'auto',
      wheelSensitivity: 0.22,
      minZoom: 0.35,
      maxZoom: 2.2,
      style: [
        {
          selector: 'node',
          style: {
            'background-color': '#64748b',
            'border-width': 2,
            'border-color': 'rgba(226, 232, 240, 0.42)',
            color: '#f8fafc',
            content: 'data(label)',
            'font-family': 'Inter',
            'font-size': 18,
            'font-weight': 900,
            height: 96,
            'line-height': 1.1,
            shape: 'roundrectangle',
            'text-halign': 'center',
            'text-valign': 'center',
            'text-outline-color': 'rgba(2, 6, 23, 0.72)',
            'text-outline-width': 3,
            width: 172
          }
        },
        { selector: '.status-running', style: { 'background-color': '#2563eb' } },
        { selector: '.status-success', style: { 'background-color': '#16a34a' } },
        { selector: '.status-requires-revision', style: { 'background-color': '#f97316' } },
        { selector: '.status-failed', style: { 'background-color': '#dc2626' } },
        { selector: '.status-waiting', style: { 'background-color': '#64748b' } },
        {
          selector: 'edge',
          style: {
            'curve-style': 'bezier',
            'line-color': 'rgba(148, 163, 184, 0.42)',
            'target-arrow-color': 'rgba(148, 163, 184, 0.62)',
            'target-arrow-shape': 'triangle',
            width: 3,
            'arrow-scale': 1.2
          }
        },
        {
          selector: '.active-path',
          style: {
            'border-color': '#67e8f9',
            'line-color': '#67e8f9',
            'target-arrow-color': '#67e8f9',
            width: 5,
            'z-index': 10
          }
        },
        {
          selector: '.active-node',
          style: {
            'border-color': '#fef08a',
            'border-width': 5,
            'z-index': 20
          } as unknown as cytoscape.Css.Node
        },
        {
          selector: '.selected-node',
          style: {
            'border-color': '#ffffff',
            'border-width': 5,
            'z-index': 30
          }
        }
      ],
      layout: {
        name: 'preset',
        fit: true,
        padding: 60
      }
    });

    this.cy.on('tap', 'node', (event) => {
      this.workflow.selectAgent(event.target.id());
    });

    setTimeout(() => this.fit(), 50);
    this.resizeObserver = new ResizeObserver(() => {
      this.cy?.resize();
      this.fit();
    });
    this.resizeObserver.observe(this.graphElement.nativeElement);
  }

  ngOnDestroy(): void {
    this.resizeObserver?.disconnect();
    this.cy?.destroy();
  }

  zoom(factor: number): void {
    if (!this.cy) {
      return;
    }
    this.cy.zoom({ level: this.cy.zoom() * factor, renderedPosition: { x: this.cy.width() / 2, y: this.cy.height() / 2 } });
  }

  fit(): void {
    this.cy?.fit(undefined, 48);
  }

  private elements(): ElementDefinition[] {
    const positions: Record<string, { x: number; y: number }> = {
      jira: { x: 120, y: 80 },
      orchestrator: { x: 120, y: 230 },
      'repo-initial': { x: -190, y: 430 },
      knowledge: { x: 0, y: 430 },
      planner: { x: 190, y: 430 },
      developer: { x: 380, y: 430 },
      reviewer: { x: 570, y: 430 },
      'repo-final': { x: 760, y: 430 }
    };

    const nodes = this.workflow.agents().map((agent) => ({
      group: 'nodes' as const,
      data: {
        id: agent.id,
        label: agent.name,
        detail: `${this.prettyStatus(agent.status)} · ${agent.executionState}`,
        status: agent.status
      },
      classes: `agent status-${agent.status}`,
      position: positions[agent.id]
    }));

    const edges = [
      ['jira', 'orchestrator'],
      ['orchestrator', 'repo-initial'],
      ['orchestrator', 'knowledge'],
      ['orchestrator', 'planner'],
      ['orchestrator', 'developer'],
      ['orchestrator', 'reviewer'],
      ['orchestrator', 'repo-final'],
      ['repo-initial', 'knowledge'],
      ['knowledge', 'planner'],
      ['planner', 'developer'],
      ['developer', 'reviewer'],
      ['reviewer', 'repo-final']
    ].map(([source, target]) => ({
      group: 'edges' as const,
      data: { id: `${source}-${target}`, source, target }
    }));

    return [...nodes, ...edges];
  }

  private prettyStatus(status: string): string {
    return status.split('-').map((part) => part[0].toUpperCase() + part.slice(1)).join(' ');
  }
}
