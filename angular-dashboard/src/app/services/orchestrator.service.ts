import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { WorkflowRequest, WorkflowResponse } from '../models/workflow-request.model';

@Injectable({
  providedIn: 'root',
})
export class OrchestratorService {
  // FastAPI orchestrator base URL (runs on port 8003)
  private apiBaseUrl = 'http://localhost:8003';

  // Individual agent service URLs (matching config.py defaults)
  private jiraServiceUrl = 'http://127.0.0.1:8001';
  private reviewerServiceUrl = 'http://127.0.0.1:8002';
  private developerServiceUrl = 'http://127.0.0.1:8000';
  private repoServiceUrl = 'http://127.0.0.1:8004';
  private knowledgeServiceUrl = 'http://127.0.0.1:8005';
  private plannerServiceUrl = 'http://127.0.0.1:8006';

  constructor(private http: HttpClient) {}

  /**
   * Start the full workflow by sending a POST to the orchestrator's /work-on-ticket
   * This is the main entry point that triggers the entire multi-agent pipeline.
   */
  startWorkflow(request: WorkflowRequest): Observable<WorkflowResponse> {
    return this.http
      .post<WorkflowResponse>(`${this.apiBaseUrl}/work-on-ticket`, request)
      .pipe(catchError(this.handleError));
  }

  /**
   * Fetch a Jira ticket directly from the Jira agent service
   */
  getJiraTicket(issueKey: string): Observable<unknown> {
    return this.http
      .get(`${this.jiraServiceUrl}/tickets/${issueKey}`)
      .pipe(catchError(this.handleError));
  }

  /**
   * Trigger the planner agent to create a plan for a ticket
   */
  planTicket(payload: unknown): Observable<unknown> {
    return this.http
      .post(`${this.plannerServiceUrl}/plan`, payload)
      .pipe(catchError(this.handleError));
  }

  /**
   * Trigger the developer agent to generate code
   */
  generateCode(payload: unknown): Observable<unknown> {
    return this.http
      .post(`${this.developerServiceUrl}/generate`, payload)
      .pipe(catchError(this.handleError));
  }

  /**
   * Trigger the developer agent to improve code based on review feedback
   */
  improveCode(payload: unknown): Observable<unknown> {
    return this.http
      .post(`${this.developerServiceUrl}/improve`, payload)
      .pipe(catchError(this.handleError));
  }

  /**
   * Trigger the reviewer agent to review code
   */
  reviewCode(payload: unknown): Observable<unknown> {
    return this.http
      .post(`${this.reviewerServiceUrl}/review`, payload)
      .pipe(catchError(this.handleError));
  }

  /**
   * Prepare a repository via the repo agent
   */
  prepareRepo(payload: unknown): Observable<unknown> {
    return this.http
      .post(`${this.repoServiceUrl}/prepare-repo`, payload)
      .pipe(catchError(this.handleError));
  }

  /**
   * Create a branch via the repo agent
   */
  createBranch(payload: unknown): Observable<unknown> {
    return this.http
      .post(`${this.repoServiceUrl}/create-branch`, payload)
      .pipe(catchError(this.handleError));
  }

  /**
   * Read files from a repository
   */
  readFiles(payload: unknown): Observable<unknown> {
    return this.http
      .post(`${this.repoServiceUrl}/read-files`, payload)
      .pipe(catchError(this.handleError));
  }

  /**
   * Apply changes to a repository
   */
  applyChanges(payload: unknown): Observable<unknown> {
    return this.http
      .post(`${this.repoServiceUrl}/apply-changes`, payload)
      .pipe(catchError(this.handleError));
  }

  /**
   * Open a pull request via the repo agent
   */
  openPullRequest(payload: unknown): Observable<unknown> {
    return this.http
      .post(`${this.repoServiceUrl}/open-pr`, payload)
      .pipe(catchError(this.handleError));
  }

  /**
   * Ensure knowledge base is up to date
   */
  ensureKnowledge(payload: unknown): Observable<unknown> {
    return this.http
      .post(`${this.knowledgeServiceUrl}/ensure-knowledge`, payload)
      .pipe(catchError(this.handleError));
  }

  /**
   * Update knowledge base with changes
   */
  updateKnowledge(payload: unknown): Observable<unknown> {
    return this.http
      .post(`${this.knowledgeServiceUrl}/update-knowledge`, payload)
      .pipe(catchError(this.handleError));
  }

  /**
   * Placeholder for future WebSocket connection for live updates
   */
  connectWebSocket(): void {
    // WebSocket connection will be implemented in a future version
    // const ws = new WebSocket('ws://localhost:8000/ws');
    // ws.onmessage = (event) => { ... };
  }

  private handleError(error: HttpErrorResponse) {
    const errorMsg = error.error?.detail || error.message || 'An unknown error occurred';
    return throwError(() => new Error(errorMsg));
  }
}