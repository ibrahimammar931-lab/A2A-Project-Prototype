export type AgentStatus = 'waiting' | 'running' | 'completed' | 'failed';

export interface Agent {
  id: string;
  name: string;
  status: AgentStatus;
  startTime: string | null;
  endTime: string | null;
  duration: string | null;
  errorMessage?: string | null;
}

export const DEFAULT_AGENTS: Agent[] = [
  { id: 'planner', name: 'Planner', status: 'waiting', startTime: null, endTime: null, duration: null },
  { id: 'developer', name: 'Developer', status: 'waiting', startTime: null, endTime: null, duration: null },
  { id: 'reviewer', name: 'Reviewer', status: 'waiting', startTime: null, endTime: null, duration: null },
  { id: 'repo', name: 'Repo', status: 'waiting', startTime: null, endTime: null, duration: null },
  { id: 'knowledge', name: 'Knowledge', status: 'waiting', startTime: null, endTime: null, duration: null },
];