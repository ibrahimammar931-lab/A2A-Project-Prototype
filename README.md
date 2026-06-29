# Simple A2A Microservices Prototype

This project is now split into small FastAPI services:

- `jira_agent.py` fetches Jira tickets.
- `reviewer_agent.py` reviews generated code.
- `developer_agent.py` generates and improves code.
- `orchestrator_agent.py` owns the full "work on this ticket" flow.

The Developer agent no longer calls Jira or Reviewer directly. The Orchestrator service coordinates those agents over HTTP.

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
`-- README.md
```

`developer_agent.py` contains the Developer Agent logic and its API.

`reviewer_agent.py` contains the Reviewer Agent logic and its API.

`jira_agent.py` contains the Jira REST API logic and its API.

`orchestrator_agent.py` contains the cross-agent workflow API.

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`:

```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_REVIEWER_MODEL=llama-3.3-70b-versatile
LOG_LEVEL=INFO

JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your_email@example.com
JIRA_API_TOKEN=your_jira_api_token_here

DEVELOPER_SERVICE_URL=http://127.0.0.1:8000
JIRA_SERVICE_URL=http://127.0.0.1:8001
REVIEWER_SERVICE_URL=http://127.0.0.1:8002
```

## Run The Services

Open four terminals.

Terminal 1:

```bash
uvicorn jira_agent:app --port 8001 --reload
```

Terminal 2:

```bash
uvicorn reviewer_agent:app --port 8002 --reload
```

Terminal 3:

```bash
uvicorn developer_agent:app --port 8000 --reload
```

Terminal 4:

```bash
uvicorn orchestrator_agent:app --port 8003 --reload
```

Developer service docs:

```text
http://127.0.0.1:8000/docs
```

Orchestrator service docs:

```text
http://127.0.0.1:8003/docs
```

Reviewer service docs:

```text
http://127.0.0.1:8002/docs
```

Jira service docs:

```text
http://127.0.0.1:8001/docs
```

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

PowerShell example:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8003/work-on-ticket" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"issue_key":"PROJ-123"}'
```

## Service Responsibilities

Jira Service:

```text
GET /tickets/{issue_key}
```

It calls Jira REST API and returns a clean `JiraTicket`.

Reviewer Service:

```text
POST /review
```

It receives a JSON agent message with the task, code, and explanation. It returns review feedback as a JSON message.

Developer Service:

```text
POST /generate
POST /improve
```

`/generate` only generates code from a task.

`/improve` improves code using review feedback.

Orchestrator Service:

```text
POST /work-on-ticket
```

`/work-on-ticket` is the complete flow:

```text
Orchestrator Service receives issue key
  -> calls Jira Service
  -> converts ticket into a task prompt
  -> calls Developer Service to generate original code
  -> calls Reviewer Service
  -> calls Developer Service to improve the code
  -> returns ticket, original code, review feedback, improved code, and messages
```

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

## Why This Is Microservices

Each service has its own FastAPI app and can run on its own port:

```text
Jira Service       -> port 8001
Reviewer Service   -> port 8002
Developer Service  -> port 8000
Orchestrator       -> port 8003
```

They communicate using HTTP JSON calls. The Orchestrator service coordinates the workflow, so individual agents keep narrow responsibilities.
