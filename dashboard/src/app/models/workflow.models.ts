export type WorkflowStatus = 'running' | 'waiting' | 'paused' | 'failed' | 'completed' | 'requires-revision';
export type WorkflowMode = 'manual' | 'automatic';
export type AgentStatus = 'waiting' | 'running' | 'success' | 'requires-revision' | 'failed';
export type MessageStatus = 'queued' | 'pending-approval' | 'sent' | 'delivered' | 'edited' | 'failed';

export interface WorkflowSummary {
  status: WorkflowStatus;
  ticket: string;
  branch: string;
  repository: string;
  runningAgent: string;
  currentAction: string;
  totalExecutionTime: string;
  progress: number;
  manualMode: boolean;
  previousAgent: string;
  currentAgent: string;
  nextAgent: string;
}

export interface AgentFileActivity {
  read: string[];
  modified: string[];
  created: string[];
}

export interface AgentNode {
  id: string;
  name: string;
  status: AgentStatus;
  executionState: string;
  startTime?: string;
  endTime?: string;
  duration: string;
  currentAction: string;
  executionCount: number;
  lastExecution: string;
  messagesSent: number;
  messagesReceived: number;
  files: AgentFileActivity;
  output: unknown;
  errors: string[];
}

export interface AgentMessage {
  id: string;
  time: string;
  sender: string;
  receiver: string;
  type: string;
  status: MessageStatus;
  duration: string;
  summary: string;
  payload: unknown;
  editedPayload?: unknown;
  userChanges: UserChange[];
}

export interface UserChange {
  time: string;
  author: string;
  description: string;
}

export interface WorkflowSnapshot {
  summary: WorkflowSummary;
  agents: AgentNode[];
  messages: AgentMessage[];
  activePath: string[];
}

export interface WorkflowCommandResult {
  command: string;
  accepted: boolean;
  timestamp: string;
}
