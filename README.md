# Simple A2A Microservices Prototype

This project is a small Agent-to-Agent microservices prototype built with FastAPI.
It separates Jira retrieval, code generation, code review, and workflow orchestration
into independent services that communicate over HTTP.

For installation, environment variables, and service startup commands, see
[SETUP.md](SETUP.md).

## Services

The current version has four services:

```text
Developer Agent    -> developer_agent.py    -> port 8000
Jira Agent         -> jira_agent.py         -> port 8001
Reviewer Agent     -> reviewer_agent.py     -> port 8002
Orchestrator Agent -> orchestrator_agent.py -> port 8003
```

## Project Structure

```text
.
|-- developer_agent.py
|-- reviewer_agent.py
|-- jira_agent.py
|-- orchestrator_agent.py
|-- schemas.py
|-- config.py
|-- requirements.txt
|-- .env.example
|-- SETUP.md
`-- README.md
```

## Architecture

The Orchestrator owns the full workflow. The Developer Agent does not call Jira or
Reviewer directly.

```text
Client
  -> Orchestrator Agent
    -> Jira Agent
    -> Developer Agent
    -> Reviewer Agent
    -> Developer Agent
```

The services exchange shared Pydantic models from `schemas.py`.

## Main Workflow

Call the Orchestrator service:

```text
POST http://127.0.0.1:8003/work-on-ticket
```

Request:

```json
{
  "issue_key": "PROJ-123"
}
```

The workflow:

```text
Orchestrator receives issue key
  -> calls Jira Agent for ticket details
  -> converts the ticket into a developer task
  -> calls Developer Agent /generate
  -> sends generated code to Reviewer Agent /review
  -> sends reviewer feedback to Developer Agent /improve
  -> returns original code, review feedback, improved code, and message trace
```

## Service APIs

### Orchestrator Agent

```text
POST /work-on-ticket
```

Coordinates the full Jira-to-code workflow.

### Jira Agent

```text
GET /tickets/{issue_key}
```

Fetches a Jira issue through Jira REST API and returns a normalized `JiraTicket`.

### Developer Agent

```text
POST /generate
POST /improve
```

`/generate` creates initial code from a task.

`/improve` revises code using reviewer feedback.

### Reviewer Agent

```text
POST /review
```

Reviews generated code and returns structured feedback.

## Example Response

```json
{
  "ticket": {
    "key": "PROJ-123",
    "summary": "Create a Flask CRUD API for users"
  },
  "original_code": {
    "code": "from flask import Flask ...",
    "explanation": "Initial implementation."
  },
  "review_feedback": {
    "approved": false,
    "issues": ["Missing input validation"],
    "suggestions": ["Add validation"],
    "security_notes": [],
    "quality_notes": []
  },
  "improved_code": {
    "code": "from flask import Flask ...",
    "explanation": "Improved implementation."
  },
  "messages": []
}
```

## Data Models

Important shared models live in `schemas.py`:

```text
GenerateRequest
GenerateResponse
JiraTicket
AgentTaskRequest
DeveloperOutput
ReviewFeedback
AgentMessage
```

## Responsibility Boundary

The service split is intentional:

```text
Jira Agent         -> Jira API access and Jira field normalization
Developer Agent    -> code generation and code improvement only
Reviewer Agent     -> code review only
Orchestrator Agent -> workflow coordination only
```

This keeps the Developer Agent from owning external service calls or workflow state,
which makes the project easier to extend with repo operations, planner agents,
retry logic, or parallel review later.
