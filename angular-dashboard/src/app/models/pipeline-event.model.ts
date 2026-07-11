/**
 * WebSocket event types sent by the backend.
 * Designed to be easily extended with new event types.
 */
export type PipelineEventType =
  | 'pipeline_started'
  | 'pipeline_finished'
  | 'pipeline_failed'
  | 'agent_started'
  | 'agent_completed'
  | 'agent_failed'
  | 'workflow_started';

/**
 * Base interface for all pipeline events.
 */
export interface PipelineEvent {
  type: PipelineEventType;
  agent?: string;
  timestamp?: string;
  message?: string;
  duration?: number;
  error?: string;
}