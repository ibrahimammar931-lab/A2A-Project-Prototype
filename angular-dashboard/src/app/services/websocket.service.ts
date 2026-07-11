import { Injectable, NgZone } from '@angular/core';
import { Observable, Subject, takeUntil, timer, tap } from 'rxjs';
import { PipelineEvent } from '../models/pipeline-event.model';

@Injectable({
  providedIn: 'root',
})
export class WebSocketService {
  private ws: WebSocket | null = null;
  private eventsSubject = new Subject<PipelineEvent>();
  private connectionStateSubject = new Subject<boolean>();
  private destroy$ = new Subject<void>();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectDelayMs = 3000;
  private wsUrl = 'ws://localhost:8003/ws';

  constructor(private ngZone: NgZone) {}

  /**
   * Connect to the WebSocket endpoint.
   */
  connect(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return;
    }

    const ws = new WebSocket(this.wsUrl);
    this.ws = ws;

    ws.onopen = () => {
      this.ngZone.run(() => {
        this.reconnectAttempts = 0;
        this.connectionStateSubject.next(true);
      });
    };

    ws.onmessage = (event: MessageEvent) => {
      this.ngZone.run(() => {
        try {
          const data: PipelineEvent = JSON.parse(event.data);
          this.eventsSubject.next(data);
        } catch {
          // Non-JSON messages are ignored
        }
      });
    };

    ws.onclose = () => {
      this.ngZone.run(() => {
        this.connectionStateSubject.next(false);
        this.attemptReconnect();
      });
    };

    ws.onerror = () => {
      // onclose will fire after onerror, so reconnect is handled there
    };
  }

  /**
   * Disconnect from the WebSocket.
   */
  disconnect(): void {
    this.destroy$.next();
    this.destroy$.complete();
    this.reconnectAttempts = this.maxReconnectAttempts; // prevent reconnect

    const ws = this.ws;
    if (ws) {
      ws.onclose = null; // prevent reconnect logic
      ws.close();
      this.ws = null;
    }
  }

  /**
   * Observable that emits each pipeline event received from the backend.
   */
  get events$(): Observable<PipelineEvent> {
    return this.eventsSubject.asObservable();
  }

  /**
   * Observable that emits connection state changes (true = connected, false = disconnected).
   */
  get connectionState$(): Observable<boolean> {
    return this.connectionStateSubject.asObservable();
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      return;
    }

    this.reconnectAttempts++;

    timer(this.reconnectDelayMs)
      .pipe(
        tap(() => this.connect()),
        takeUntil(this.destroy$),
      )
      .subscribe();
  }
}