// Matches GenerateRequest from schemas.py
export interface WorkflowRequest {
  issue_key: string;
  base_branch: string;
}

// Matches GenerateResponse from schemas.py
export interface WorkflowResponse {
  ticket?: JiraTicket | null;
  original_code: DeveloperOutput;
  review_feedback: ReviewFeedback;
  improved_code: DeveloperOutput;
  messages: AgentMessage[];
  planning_result?: PlanningResult | null;
  repo?: RepoInfo | null;
  branch?: BranchResponse | null;
  repo_files?: RepoFile[];
  applied_changes?: ApplyChangesResponse | null;
  diff?: RepoDiffResponse | null;
  commit?: CommitResponse | null;
  push?: PushResponse | null;
  pull_request?: PullRequestResponse | null;
}

// Supporting types matching schemas.py

export interface JiraTicket {
  key: string;
  url: string;
  summary: string;
  description: string;
  issue_type?: string | null;
  status?: string | null;
  priority?: string | null;
  assignee?: string | null;
  reporter?: string | null;
  labels: string[];
  components: string[];
  custom_fields: Record<string, unknown>;
}

export interface RepoInfo {
  repo_id: string;
  path: string;
  current_branch?: string | null;
  remote_url: string;
  status: string;
}

export interface BranchResponse {
  repo_id: string;
  branch: string;
  base_branch: string;
}

export interface RepoFile {
  path: string;
  content: string;
}

export interface FileChange {
  path: string;
  action: string;
  content?: string | null;
}

export interface PlanningResult {
  task_summary: string;
  requirements: string[];
  implementation_steps: string[];
  likely_modules: string[];
  likely_existing_files: string[];
  new_files: string[];
  acceptance_criteria: string[];
  risks: string[];
  complexity: 'Low' | 'Medium' | 'High';
}

export interface DeveloperOutput {
  explanation: string;
  changes: FileChange[];
  code: string;
}

export interface ReviewIssue {
  category: string;
  severity: string;
  summary: string;
  recommendation: string;
  location?: string | null;
  ticket_relevant: boolean;
}

export interface ReviewFeedback {
  approved: boolean;
  decision: string;
  summary: string;
  issues: string[];
  suggestions: string[];
  security_notes: string[];
  quality_notes: string[];
  blocking_issues: ReviewIssue[];
  optional_suggestions: ReviewIssue[];
  requires_revision: boolean;
  rationale: string;
}

export interface AgentMessage {
  sender: string;
  receiver: string;
  message_type: string;
  payload: Record<string, unknown>;
}

export interface ApplyChangesResponse {
  repo_id: string;
  changed_files: string[];
  branch: string;
  commit_shas: string[];
}

export interface RepoDiffResponse {
  repo_id: string;
  diff: string;
}

export interface CommitResponse {
  repo_id: string;
  commit_sha: string;
  message: string;
}

export interface PushResponse {
  repo_id: string;
  branch: string;
  remote: string;
}

export interface PullRequestResponse {
  repo_id: string;
  number: number;
  url: string;
  title: string;
}