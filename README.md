# Simple A2A Microservices Prototype

This project is now split into small FastAPI services:

- `jira_agent.py` fetches Jira tickets.
- `knowledge_agent.py` maintains repository knowledge.
- `planner_agent.py` produces implementation plans from tickets and knowledge.
- `repo_agent.py` reads and updates GitHub repositories.
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
|-- knowledge_agent.py
|-- planner_agent.py
|-- repo_agent.py
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

`knowledge_agent.py` maintains structured repository knowledge.

`planner_agent.py` plans implementation work without generating code or editing files.

`repo_agent.py` reads selected files and applies GitHub API changes.

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
GROQ_PLANNER_MODEL=llama-3.3-70b-versatile
LOG_LEVEL=INFO

JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your_email@example.com
JIRA_API_TOKEN=your_jira_api_token_here

DEVELOPER_SERVICE_URL=http://127.0.0.1:8000
JIRA_SERVICE_URL=http://127.0.0.1:8001
REVIEWER_SERVICE_URL=http://127.0.0.1:8002
REPO_SERVICE_URL=http://127.0.0.1:8004
KNOWLEDGE_SERVICE_URL=http://127.0.0.1:8005
PLANNER_SERVICE_URL=http://127.0.0.1:8006
```

## Run The Services

Open seven terminals.

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

Terminal 5:

```bash
uvicorn repo_agent:app --port 8004 --reload
```

Terminal 6:

```bash
uvicorn knowledge_agent:app --port 8005 --reload
```

Terminal 7:

```bash
uvicorn planner_agent:app --port 8006 --reload
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

Planner service docs:

```text
http://127.0.0.1:8006/docs
```

## Main Workflow

Call the Orchestrator service:

```text
POST http://127.0.0.1:8003/work-on-ticket
```

Request:

```json
{
  "issue_key": "PROJ-123",
  "base_branch": "main"
}
```

The Orchestrator uses `GITHUB_REPO_URL` from `.env`. The Planner Agent chooses which existing files to read from the knowledge base and which new files should be created.

PowerShell example:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8003/work-on-ticket" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"issue_key":"PROJ-123","base_branch":"main"}'
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
  -> asks Repo Service to prepare the repo
  -> asks Knowledge Agent to ensure repository knowledge exists
  -> asks Planner Agent to produce a structured plan
  -> asks Repo Service to read Planner likely_existing_files
  -> calls Developer Service to generate original code
  -> calls Reviewer Service
  -> calls Developer Service to improve the code
  -> returns ticket, original code, review feedback, improved code, and messages
```

The Planner Agent never calls the Repository Agent or Developer Agent directly. Only the Orchestrator coordinates those calls.

Repo Service:

```text
POST /prepare-repo
POST /create-branch
POST /read-files
POST /apply-changes
POST /open-pr
```

The Repo service owns repository operations. It uses the local clone for reading files, and GitHub API for creating ticket branches, applying structured file changes, committing changes, and opening pull requests.

Prepare the configured repo:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8004/prepare-repo" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{}'
```

Create a branch:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8004/create-branch" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"repo_url":"https://github.com/owner/project.git","issue_key":"PROJ-123","title":"Add user API","base_branch":"main"}'
```

Open a pull request after `apply-changes`:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8004/open-pr" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"repo_url":"https://github.com/owner/project.git","issue_key":"PROJ-123","title":"Add user API","summary":"Adds the user API implementation and tests.","base_branch":"main"}'
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
  "repo": {
    "repo_id": "owner-project",
    "path": "C:\\Users\\ibrah\\Desktop\\A2A\\workspaces\\owner-project",
    "current_branch": "main",
    "remote_url": "https://github.com/owner/project.git",
    "status": "updated"
  },
  "branch": {
    "repo_id": "owner-project",
    "branch": "agent/PROJ-123-create-a-flask-crud-api-for-users",
    "base_branch": "main"
  },
  "repo_files": [
    {
      "path": "app/main.py",
      "content": "..."
    }
  ],
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
