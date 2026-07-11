import { Injectable, OnDestroy } from '@angular/core';
import { BehaviorSubject, Observable, Subject, Subscription, takeUntil } from 'rxjs';
import { Agent, AgentStatus, DEFAULT_AGENTS } from '../models/agent.model';
import { LogEntry } from '../models/log.model';
import { PipelineEvent } from '../models/pipeline-event.model';
import { WebSocketService } from './websocket.service';

/**
 * Maps agent names (from backend events) to agent IDs used in the dashboard.
 */
const AGENT_NAME_TO_ID: Record<string, string> = {
  planner: 'planner',
  developer: 'developer',
  reviewer: 'reviewer',
  repo: 'repo',
  knowledge: 'knowledge',
  planner_agent: 'planner',
  developer_agent: 'developer',
  reviewer_agent: 'reviewer',
  repo_agent: 'repo',
  knowledge_agent: 'knowledge',
};

function normalizeAgentName(name: string): string {
  const lower = name.toLowerCase().trim();
  return AGENT_NAME_TO_ID[lower] || lower;
}

@Injectable({
  providedIn: 'root',
})
export class PipelineService implements OnDestroy {
  private agentsSubject = new BehaviorSubject<Agent[]>([...DEFAULT_AGENTS]);
  private logsSubject = new BehaviorSubject<LogEntry[]>([]);
  private selectedAgentSubject = new BehaviorSubject<Agent | null>(null);
  private pipelineRunningSubject = new BehaviorSubject<boolean>(false);
  private pipelineFinishedSubject = new BehaviorSubject<boolean>(false);
  private pipelineFailedSubject = new BehaviorSubject<boolean>(false);
  private destroy$ = new Subject<void>();

  private wsSubscription: Subscription | null = null;

  constructor(private wsService: WebSocketService) {
    this.connectToWebSocket();
  }

  ngOnDestroy(): void {
    this.disconnect();
  }

  /**
   * Connect to the WebSocket and start listening for pipeline events.
   */
  connectToWebSocket(): void {
    this.wsService.connect();

    this.wsSubscription?.unsubscribe();
    this.wsSubscription = this.wsService.events$
      .pipe(takeUntil(this.destroy$))
      .subscribe((event) => this.handleEvent(event));
  }

  /**
   * Disconnect from the WebSocket and reset state.
   */
  disconnect(): void {
    this.destroy$.next();
    this.destroy$.complete();
    this.wsSubscription?.unsubscribe();
    this.wsService.disconnect();
  }

  /**
   * Reset the pipeline state to initial values.
   */
  reset(): void {
    this.agentsSubject.next([...DEFAULT_AGENTS]);
    this.logsSubject.next([]);
    this.selectedAgentSubject.next(null);
    this.pipelineRunningSubject.next(false);
    this.pipelineFinishedSubject.next(false);
    this.pipelineFailedSubject.next(false);
  }

  // --- Observables ---

  get agents$(): Observable<Agent[]> {
    return this.agentsSubject.asObservable();
  }

  get logs$(): Observable<LogEntry[]> {
    return this.logsSubject.asObservable();
  }

  get selectedAgent$(): Observable<Agent | null> {
    return this.selectedAgentSubject.asObservable();
  }

  get pipelineRunning$(): Observable<boolean> {
    return this.pipelineRunningSubject.asObservable();
  }

  get pipelineFinished$(): Observable<boolean> {
    return this.pipelineFinishedSubject.asObservable();
  }

  get pipelineFailed$(): Observable<boolean> {
    return this.pipelineFailedSubject.asObservable();
  }

  /**
   * Select an agent to show in the detail panel.
   */
  selectAgent(agent: Agent): void {
    this.selectedAgentSubject.next(agent);
  }

  // --- Event handling ---

  private handleEvent(event: PipelineEvent): void {
    const timestamp = this.formatTimestamp(event.timestamp);

    // Add a log entry for every event
    this.addLog({
      time: timestamp,
      agent: event.agent || 'system',
      message: event.message || this.defaultMessage(event),
    });

    switch (event.type) {
      case 'pipeline_started':
      case 'workflow_started':
        this.reset();
        this.pipelineRunningSubject.next(true);
        this.pipelineFinishedSubject.next(false);
        this.pipelineFailedSubject.next(false);
        break;

      case 'agent_started':
        // If the agent was previously completed, reset it to waiting first
        // so it can transition to running again (e.g. repo agent called twice)
        this.resetAgentIfNeeded(event.agent);
        this.updateAgentStatus(event.agent, 'running', timestamp);
        break;

      case 'agent_completed':
        this.updateAgentStatus(event.agent, 'completed', timestamp, event.duration);
        break;

      case 'agent_failed':
        this.updateAgentStatus(event.agent, 'failed', timestamp, undefined, event.error);
        break;

      case 'pipeline_finished':
        this.pipelineRunningSubject.next(false);
        this.pipelineFinishedSubject.next(true);
        this.pipelineFailedSubject.next(false);
        break;

      case 'pipeline_failed':
        this.pipelineRunningSubject.next(false);
        this.pipelineFinishedSubject.next(true);
        this.pipelineFailedSubject.next(true);
        break;
    }
  }

  /**
   * If an agent is currently in 'completed' or 'failed' state and is being
   * called again, reset it to 'waiting' first so the UI shows a clean transition.
   */
  private resetAgentIfNeeded(agentName: string | undefined): void {
    if (!agentName) return;

    const id = normalizeAgentName(agentName);
    const agents = this.agentsSubject.getValue();
    const index = agents.findIndex((a) => a.id === id);
    if (index === -1) return;

    const current = agents[index];
    if (current.status === 'completed' || current.status === 'failed') {
      const updated = [...agents];
      updated[index] = {
        ...current,
        status: 'waiting',
        startTime: null,
        endTime: null,
        duration: null,
        errorMessage: null,
      };
      this.agentsSubject.next(updated);
    }
  }

  private updateAgentStatus(
    agentName: string | undefined,
    status: AgentStatus,
    timestamp: string,
    duration?: number,
    error?: string,
  ): void {
    if (!agentName) return;

    const id = normalizeAgentName(agentName);
    const agents = this.agentsSubject.getValue();
    const index = agents.findIndex((a) => a.id === id);

    if (index === -1) return;

    const updated = [...agents];
    const agent = { ...updated[index] };
    agent.status = status;

    if (status === 'running') {
      agent.startTime = timestamp;
      agent.endTime = null;
      agent.duration = null;
      agent.errorMessage = null;
    } else if (status === 'completed') {
      agent.endTime = timestamp;
      agent.duration = duration !== undefined ? `${duration.toFixed(1)}s` : null;
      agent.errorMessage = null;
    } else if (status === 'failed') {
      agent.endTime = timestamp;
      agent.duration = duration !== undefined ? `${duration.toFixed(1)}s` : null;
      agent.errorMessage = error || 'Unknown error';
    }

    updated[index] = agent;
    this.agentsSubject.next(updated);

    // Auto-select the running agent
    if (status === 'running') {
      this.selectedAgentSubject.next(agent);
    }
  }

  private addLog(log: LogEntry): void {
    const logs = this.logsSubject.getValue();
    this.logsSubject.next([...logs, log]);
  }

  private formatTimestamp(ts?: string): string {
    if (ts) {
      try {
        const date = new Date(ts);
        if (!isNaN(date.getTime())) {
          return date.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
          });
        }
      } catch {
        // fall through
      }
      return ts;
    }
    return new Date().toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  }

  private defaultMessage(event: PipelineEvent): string {
    const agent = event.agent || 'System';
    switch (event.type) {
      case 'pipeline_started':
        return 'Pipeline started';
      case 'workflow_started':
        return 'Workflow started';
      case 'agent_started':
        return `${agent} started`;
      case 'agent_completed':
        return `${agent} completed`;
      case 'agent_failed':
        return `${agent} failed: ${event.error || 'Unknown error'}`;
      case 'pipeline_finished':
        return 'Pipeline finished';
      case 'pipeline_failed':
        return 'Pipeline failed';
      default:
        return `${agent} ${event.type}`;
    }
  }
}