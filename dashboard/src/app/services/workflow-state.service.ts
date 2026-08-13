import { HttpClient } from '@angular/common/http';
import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { Observable, Subject, catchError, interval, of, startWith, switchMap, tap } from 'rxjs';
import { AgentMessage, AgentNode, WorkflowCommandResult, WorkflowSnapshot, WorkflowMode, WorkflowStep, WorkspaceMode } from '../models/workflow.models';

const API_BASE = '/api/workflow';
const WS_URL = 'ws://localhost:8010/ws/workflow';

@Injectable({ providedIn: 'root' })
export class WorkflowStateService {
  private readonly http = inject(HttpClient);
  private readonly commandEvents = new Subject<WorkflowCommandResult>();

  readonly snapshot = signal<WorkflowSnapshot>(createMockSnapshot());
  readonly selectedAgentId = signal<string | null>('planner');
  readonly selectedMessageId = signal<string | null>('msg-planner-developer');

  readonly summary = computed(() => this.snapshot().summary);
  readonly agents = computed(() => this.snapshot().agents);
  readonly messages = computed(() => this.snapshot().messages);
  readonly activePath = computed(() => this.snapshot().activePath);
  readonly workflowSteps = computed(() => {
    const snapshot = this.snapshot();
    return snapshot.workflowSteps?.length
      ? snapshot.workflowSteps
      : fallbackWorkflowSteps(snapshot.agents);
  });
  readonly availableModels = signal<{ id: string; label: string; provider: string }[]>([]);
  readonly modelSelection = signal<Record<string, string>>({});
  readonly currentMode = signal<WorkflowMode>('manual');
  readonly isManualMode = computed(() => this.currentMode() === 'manual');
  readonly isAutomaticMode = computed(() => this.currentMode() === 'automatic');
  readonly autoModelSelection = signal<boolean>(false);
  readonly isAutoModelMode = computed(() => this.autoModelSelection());
  readonly selectedAgent = computed(() => {
    const selectedId = this.selectedAgentId();
    return this.snapshot().agents.find((agent) => agent.id === selectedId) ?? null;
  });
  readonly selectedMessage = computed(() => {
    const selectedId = this.selectedMessageId();
    return this.snapshot().messages.find((message) => message.id === selectedId) ?? null;
  });
  readonly commandResults$: Observable<WorkflowCommandResult> = this.commandEvents.asObservable();

  constructor() {
    this.connectWebSocket();
    effect(() => {
      const running = this.summary().status === 'running';
      if (!running) {
        return;
      }
    });
  }

  refresh(): Observable<WorkflowSnapshot> {
    return this.http.get<WorkflowSnapshot>(`${API_BASE}/state`).pipe(
      tap((snapshot) => this.snapshot.set(snapshot)),
      catchError(() => of(this.snapshot()))
    );
  }

  pollFallback(): Observable<WorkflowSnapshot> {
    return interval(8000).pipe(
      startWith(0),
      switchMap(() => this.refresh())
    );
  }

  selectAgent(agentId: string): void {
    this.selectedAgentId.set(agentId);
  }

  selectMessage(messageId: string): void {
    this.selectedMessageId.set(messageId);
  }

  setMode(mode: WorkflowMode): void {
    this.http.post(`${API_BASE}/set-mode`, { mode }).pipe(
      catchError(() => of({ command: 'set-mode', accepted: true, mode, timestamp: new Date().toISOString() }))
    ).subscribe((result: any) => {
      this.currentMode.set(result.mode);
    });
  }

  fetchMode(): void {
    this.http.get<{ mode: WorkflowMode }>(`${API_BASE}/mode`).pipe(
      catchError(() => of({ mode: 'manual' as WorkflowMode }))
    ).subscribe((result) => {
      this.currentMode.set(result.mode);
    });
  }

  loadAvailableModels(): void {
    this.http.get<{ id: string; label: string; provider: string }[]>(`${API_BASE}/available-models`).pipe(
      catchError(() => of([]))
    ).subscribe((models) => this.availableModels.set(models));
  }

  loadModelSelection(): void {
    this.http.get<Record<string, string>>(`${API_BASE}/model-selection`).pipe(
      catchError(() => of({}))
    ).subscribe((selection) => this.modelSelection.set(selection));
  }

  saveModelSelection(selection: Partial<Record<string, string>>): void {
    this.http.post<Record<string, string>>(`${API_BASE}/model-selection`, selection).pipe(
      catchError(() => of(this.modelSelection()))
    ).subscribe((updated) => this.modelSelection.set(updated));
  }

  fetchAutoModelSelection(): void {
    this.http.get<{ enabled: boolean }>(`${API_BASE}/auto-model-selection`).pipe(
      catchError(() => of({ enabled: false }))
    ).subscribe((result) => {
      this.autoModelSelection.set(result.enabled);
    });
  }

  setAutoModelSelection(enabled: boolean): void {
    this.http.post<{ enabled: boolean }>(`${API_BASE}/set-auto-model-selection`, { enabled }).pipe(
      catchError(() => of({ enabled: this.autoModelSelection() }))
    ).subscribe((result) => {
      this.autoModelSelection.set(result.enabled);
    });
  }

  toggleMode(): void {
    const newMode: WorkflowMode = this.currentMode() === 'manual' ? 'automatic' : 'manual';
    this.setMode(newMode);
  }

  startWorkflow(
    issueKey = this.summary().ticket,
    baseBranch = this.summary().branch,
    existingBranch = '',
    openPr = true,
    repoUrl = '',
    workspaceMode: WorkspaceMode = 'git',
    localPath = ''
  ): void {
    this.command('start', {
      issue_key: issueKey,
      base_branch: baseBranch,
      existing_branch: existingBranch,
      open_pr: openPr,
      repo_url: repoUrl,
      workspace_mode: workspaceMode,
      local_path: localPath
    });
    if (this.isManualMode()) {
      this.patchSummary({ status: 'waiting', runningAgent: 'None', currentAction: 'Workflow started. Jira is waiting for approval.' });
    } else {
      this.patchSummary({ status: 'running', currentAction: 'Automatic workflow in progress...' });
    }
  }

  pauseWorkflow(): void {
    this.command('pause');
    this.patchSummary({ status: 'paused', currentAction: 'Workflow paused by operator' });
  }

  resumeWorkflow(): void {
    this.command('resume');
    this.patchSummary({ status: 'running', currentAction: 'Manual execution resumed' });
  }

  stopWorkflow(): void {
    this.command('stop');
    this.patchSummary({ status: 'failed', currentAction: 'Workflow stopped' });
  }

  restartWorkflow(existingBranch = '', openPr = true, repoUrl = '', workspaceMode: WorkspaceMode = 'git', localPath = ''): void {
    this.command('restart', {
      issue_key: this.summary().ticket,
      base_branch: this.summary().branch,
      existing_branch: existingBranch,
      open_pr: openPr,
      repo_url: repoUrl,
      workspace_mode: workspaceMode,
      local_path: localPath
    });
    this.snapshot.set(createMockSnapshot());
  }

  exportExecutionLog(): void {
    this.command('export-log');
    const blob = new Blob([JSON.stringify(this.snapshot(), null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `workflow-execution-${new Date().toISOString()}.json`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  runNextAgent(): void {
    this.command('run-next-agent');
    this.patchSummary({ status: 'running', runningAgent: this.summary().currentAgent, currentAction: `Running ${this.summary().currentAgent}` });
  }

  rerunCurrentAgent(): void {
    this.command('rerun-current-agent');
    this.patchSummary({ status: 'running', currentAction: `Re-running ${this.summary().currentAgent}` });
  }

  skipAgent(): void {
    this.command('skip-agent');
    this.patchSummary({ currentAction: `${this.summary().currentAgent} skipped by operator` });
  }

  cancelWorkflow(): void {
    this.command('cancel');
    this.patchSummary({ status: 'failed', currentAction: 'Workflow cancelled' });
  }

  saveEditedMessage(messageId: string, editedPayload: unknown, description: string): void {
    this.command('save-edited-message', { messageId, editedPayload, description });
    const snapshot = this.snapshot();
    this.snapshot.set({
      ...snapshot,
      messages: snapshot.messages.map((message) => message.id === messageId
        ? {
            ...message,
            status: 'pending-approval',
            editedPayload,
            userChanges: [
              ...message.userChanges,
              {
                time: new Date().toISOString(),
                author: 'Dashboard operator',
                description
              }
            ]
          }
        : message)
    });
  }

  sendEditedMessage(messageId: string): void {
    this.command('send-edited-message', { messageId });
    const snapshot = this.snapshot();
    this.snapshot.set({
      ...snapshot,
      messages: snapshot.messages.map((message) => message.id === messageId
        ? { ...message, status: 'sent', payload: message.editedPayload ?? message.payload }
        : message)
    });
  }

  copyJson(payload: unknown): void {
    void navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
  }

  downloadJson(filename: string, payload: unknown): void {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  private command(command: string, payload: Record<string, unknown> = {}): void {
    this.http.post<WorkflowCommandResult>(`${API_BASE}/${command}`, payload).pipe(
      catchError(() => of({ command, accepted: true, timestamp: new Date().toISOString() }))
    ).subscribe((result) => {
      this.commandEvents.next(result);
      this.refresh().subscribe();
    });
  }

  private patchSummary(patch: Partial<WorkflowSnapshot['summary']>): void {
    const snapshot = this.snapshot();
    this.snapshot.set({ ...snapshot, summary: { ...snapshot.summary, ...patch } });
  }

  private connectWebSocket(): void {
    if (!('WebSocket' in window)) {
      this.pollFallback().subscribe();
      return;
    }

    try {
      const socket = new WebSocket(WS_URL);
      socket.onmessage = (event) => {
        const snapshot = JSON.parse(event.data) as WorkflowSnapshot;
        this.snapshot.set(snapshot);
      };
      socket.onerror = () => this.pollFallback().subscribe();
    } catch {
      this.pollFallback().subscribe();
    }
  }
}

function createMockSnapshot(): WorkflowSnapshot {
  const agents: AgentNode[] = [
    agent('jira', 'Jira', 'success', 'Ticket loaded', 1, 0, 1, {
      ticket: 'A2A-184',
      title: 'Expose multi-agent workflow control plane',
      labels: ['dashboard', 'manual-mode']
    }),
    agent('orchestrator', 'Orchestrator', 'success', 'Manual gate active', 5, 4, 6, {
      mode: 'manual',
      previous_agent: 'Planner',
      next_agent: 'Developer'
    }),
    agent('repo-initial', 'Repo', 'success', 'Workspace prepared', 2, 1, 3, {
      branch: 'feature/agent-control-center',
      base: 'main'
    }),
    agent('knowledge', 'Knowledge', 'success', 'Context hydrated', 3, 2, 2, {
      sources: ['README.md', 'schemas.py', 'orchestrator_agent.py']
    }),
    agent('planner', 'Planner', 'requires-revision', 'Awaiting operator edit', 4, 3, 2, {
      requirements: ['Create a mission-control dashboard', 'Pause before Developer starts'],
      implementation_steps: ['Render pipeline graph', 'Inspect agent output', 'Allow editing planner payload'],
      acceptance_criteria: ['Operator can approve next agent', 'Edited payload is persisted']
    }),
    agent('developer', 'Developer', 'waiting', 'Waiting for approval', 0, 2, 0, {
      file_changes: [
        { path: 'routes/tasks.py', operation: 'modify' },
        { path: 'services/task_service.py', operation: 'modify' },
        { path: 'services/task_statistics.py', operation: 'create' }
      ]
    }),
    agent('reviewer', 'Reviewer', 'waiting', 'Queued after Developer', 0, 0, 0, {
      blocking_issues: [],
      suggestions: [],
      decision: 'pending'
    }),
    agent('repo-final', 'Repo', 'waiting', 'Commit and PR pending', 0, 0, 0, {
      commits: [],
      pr_url: null
    })
  ];

  return {
    summary: {
      status: 'requires-revision',
      ticket: 'A2A-184',
      branch: 'feature/agent-control-center',
      repository: 'ibrahimammar931/lab-real-test',
      runningAgent: 'None',
      currentAction: 'Planner completed. Developer is waiting for approval.',
      totalExecutionTime: '00:18:42',
      progress: 56,
      manualMode: true,
      workspaceMode: 'git',
      previousAgent: 'Planner',
      currentAgent: 'Developer',
      nextAgent: 'Reviewer'
    },
    agents,
    messages: [
      {
        id: 'msg-planner-developer',
        time: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
        sender: 'Planner',
        receiver: 'Developer',
        type: 'planning.completed',
        status: 'pending-approval',
        duration: '01:12',
        summary: 'Planning completed',
        payload: {
          likely_files: ['routes/tasks.py', 'services/task_service.py'],
          requirements: ['Add workflow controls', 'Support manual approvals'],
          implementation_steps: ['Create dashboard components', 'Wire workflow service'],
          acceptance_criteria: ['Can edit payload before delivery', 'Can run next agent manually'],
          comments: []
        },
        userChanges: []
      },
      {
        id: 'msg-knowledge-planner',
        time: new Date(Date.now() - 1000 * 60 * 12).toISOString(),
        sender: 'Knowledge',
        receiver: 'Planner',
        type: 'context.ready',
        status: 'delivered',
        duration: '00:31',
        summary: 'Repository context delivered',
        payload: {
          files_read: ['README.md', 'schemas.py', 'orchestrator_agent.py'],
          constraints: ['Do not alter Python workflow behavior']
        },
        userChanges: []
      }
    ],
    activePath: ['jira', 'orchestrator', 'repo-initial', 'knowledge', 'planner', 'developer']
  };
}

function fallbackWorkflowSteps(agents: AgentNode[]): WorkflowStep[] {
  const preferredOrder = ['jira', 'model-selector', 'repo-initial', 'knowledge', 'planner', 'developer', 'reviewer', 'repo-final'];
  const byId = new Map(agents.map((agent) => [agent.id, agent]));
  return preferredOrder
    .filter((agentId) => byId.has(agentId))
    .map((agentId) => ({
      id: agentId,
      agentId,
      name: byId.get(agentId)?.name === 'Repo' ? 'Repository' : byId.get(agentId)?.name ?? agentId
    }));
}

function agent(
  id: string,
  name: string,
  status: AgentNode['status'],
  executionState: string,
  executionCount: number,
  messagesReceived: number,
  messagesSent: number,
  output: unknown
): AgentNode {
  return {
    id,
    name,
    status,
    executionState,
    startTime: new Date(Date.now() - 1000 * 60 * (20 - executionCount)).toISOString(),
    endTime: status === 'waiting' || status === 'running' ? undefined : new Date(Date.now() - 1000 * 60 * (12 - executionCount)).toISOString(),
    duration: executionCount ? `00:0${Math.min(executionCount + 1, 9)}:${executionCount * 7}` : '00:00:00',
    currentAction: executionState,
    executionCount,
    lastExecution: executionCount ? new Date(Date.now() - 1000 * 60 * executionCount).toISOString() : 'Never',
    messagesSent,
    messagesReceived,
    files: {
      read: ['README.md', 'schemas.py'].slice(0, Math.min(executionCount, 2)),
      modified: status === 'running' ? ['dashboard/src/app/app.component.ts'] : [],
      created: status === 'success' ? [] : []
    },
    output,
    errors: status === 'failed' ? ['Agent returned a non-zero exit code'] : []
  };
}
