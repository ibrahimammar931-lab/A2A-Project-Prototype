import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { WorkflowRequest, WorkflowResponse } from '../models/workflow-request.model';

@Injectable({
  providedIn: 'root',
})
export class OrchestratorService {
  // Configure this to point to your FastAPI orchestrator
  private apiBaseUrl = 'http://localhost:8000';

  constructor(private http: HttpClient) {}

  /**
   * Start the workflow by sending a POST to /work-on-ticket
   */
  startWorkflow(request: WorkflowRequest): Observable<WorkflowResponse> {
    return this.http
      .post<WorkflowResponse>(`${this.apiBaseUrl}/work-on-ticket`, request)
      .pipe(catchError(this.handleError));
  }

  /**
   * Pause the workflow (placeholder endpoint)
   */
  pauseWorkflow(): Observable<{ message: string }> {
    return this.http
      .post<{ message: string }>(`${this.apiBaseUrl}/workflow/pause`, {})
      .pipe(catchError(this.handleError));
  }

  /**
   * Resume the workflow (placeholder endpoint)
   */
  resumeWorkflow(): Observable<{ message: string }> {
    return this.http
      .post<{ message: string }>(`${this.apiBaseUrl}/workflow/resume`, {})
      .pipe(catchError(this.handleError));
  }

  /**
   * Stop the workflow (placeholder endpoint)
   */
  stopWorkflow(): Observable<{ message: string }> {
    return this.http
      .post<{ message: string }>(`${this.apiBaseUrl}/workflow/stop`, {})
      .pipe(catchError(this.handleError));
  }

  /**
   * Placeholder for future WebSocket connection
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