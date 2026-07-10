export interface WorkflowRequest {
  issue_key: string;
  base_branch: string;
}

export interface WorkflowResponse {
  message?: string;
  detail?: string;
  [key: string]: unknown;
}