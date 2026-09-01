# Internship Report - A2A Multi-Agent Automation System

## 1. Introduction

### 1.1 Context

This internship project focused on the design and implementation of a local prototype for an A2A multi-agent automation system. The objective of the system is to automate a software development workflow that starts from a Jira ticket, analyzes the target repository, plans the implementation, generates code changes, reviews them, applies them to a GitHub branch, and optionally opens a pull request.

[FILL IN: internship period, academic program, department, supervisor name, and host company/team context.]

### 1.2 Objectives

The main objectives of the project were:

- Build a modular multi-agent workflow where each agent has a clear responsibility.
- Connect the workflow to external development tools, mainly Jira and GitHub.
- Use large language models for planning, code generation, review, repository knowledge extraction, and model selection.
- Provide a dashboard that allows an operator to monitor execution, control the workflow manually, inspect agent messages, and edit payloads before they are sent to the next agent.
- Support both GitHub-based execution and a local-folder workflow mode.

[FILL IN: personal objectives assigned by the company or internship supervisor.]

## 2. Company Presentation

[FILL IN: company name, sector of activity, products/services, size, departments, technical team organization, and internship host team.]

[FILL IN: description of the company's software development process and why automation was relevant in this environment.]

## 3. Context and Problem Statement

Modern software development teams often manage feature requests and bug reports through ticketing systems such as Jira, then implement the corresponding changes in Git repositories hosted on platforms such as GitHub. This process involves several repetitive steps: reading the ticket, identifying the relevant files, understanding the existing codebase, planning the implementation, writing the code, reviewing the change, committing it, and preparing a pull request.

The A2A project addresses this workflow by decomposing it into specialized agents. Instead of using a single monolithic automation script, the system defines separate FastAPI services for repository handling, knowledge extraction, planning, development, review, model selection, and orchestration. The orchestrator coordinates these services through HTTP APIs and exposes a dashboard-facing control plane under `/api/workflow/*`.

The problem solved by the system can therefore be summarized as follows: how to transform a Jira issue into a reviewed and applied code change while preserving traceability, operator control, repository context, and structured communication between specialized agents.

The current repository also shows signs of active prototyping and refactoring. For example, the README describes a Jira Agent service, and `agents/orchestrator_agent.py` calls `GET {JIRA_SERVICE_URL}/tickets/{issue_key}`, but no current `agents/jira_agent.py` file is present in the checked repository. Similarly, `README.md` lists the orchestrator on port `8003`, while `run_all.ps1`, `dashboard/proxy.conf.json`, and `dashboard/src/app/services/workflow-state.service.ts` use port `8010`. These points should be clarified before final delivery or deployment.

## 4. Technical Environment

### 4.1 Backend

The backend is implemented in Python and organized as multiple FastAPI services.

Main Python libraries from `requirements.txt` and code imports:

| Technology | Usage |
|---|---|
| Python | Main backend language for agents and shared schemas. |
| FastAPI `0.115.6` | HTTP API framework used by every agent service. |
| Uvicorn `0.34.0` | ASGI server used to run each FastAPI service. |
| Pydantic `2.10.4` | Shared request/response validation in `shared/schemas.py`. |
| httpx `0.28.1` | HTTP client for service-to-service calls and GitHub API calls. |
| python-dotenv `1.0.1` | Loads `.env` configuration in `shared/config.py`. |
| LiteLLM `1.55.4` | Unified model API used by the Developer, Reviewer, Planner, Knowledge, and Model Selector agents. |
| openai `1.59.7` | Installed dependency, available for OpenAI-compatible model providers. |
| subprocess / git CLI | Used by `agents/repo_agent.py` and `agents/knowledge_agent.py` for local Git operations. |
| pathlib, os, logging, json, re, shutil | Standard-library utilities for filesystem, configuration, logging, serialization, and text processing. |

External APIs and services:

- Jira API: expected through `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN`; consumed through `JIRA_SERVICE_URL` by the orchestrator.
- GitHub API: used in `agents/repo_agent.py` for branch creation, file updates through the Contents API, file deletion, and pull request creation.
- LLM providers through LiteLLM: model entries in `shared/available_models.py` include DeepSeek, Gemini, Groq, and OpenRouter models, each gated by provider-specific API keys.

### 4.2 Frontend

The dashboard is implemented in Angular.

Main frontend technologies from `dashboard/package.json` and imports:

| Technology | Usage |
|---|---|
| Angular `19.2.x` | Frontend framework for the dashboard. |
| TypeScript `~5.7.2` | Frontend language. |
| Angular Material / CDK | UI components such as buttons, forms, sidenav, cards, icons, progress bars, expansion panels, toggles, and snackbars. |
| RxJS `~7.8.0` | Observables, polling fallback, and HTTP/WebSocket-related state updates. |
| Cytoscape `^3.32.0` | Pipeline graph visualization in `pipeline-graph.component.ts`. |
| SCSS | Styling through `dashboard/src/styles.scss` and inline component styles. |

## 5. System Architecture

The system follows a service-oriented multi-agent architecture. Each agent is a FastAPI application with a dedicated role. The services communicate mainly through HTTP JSON requests. Shared schemas are defined in `shared/schemas.py` to keep data contracts consistent across services.

### 5.1 Agent and Service Responsibilities

| Service | File | Default port | Main endpoints | Responsibility |
|---|---:|---:|---|---|
| Developer Agent | `agents/developer_agent.py` | `8000` | `POST /generate`, `POST /improve` | Generates initial code changes and revises them after review feedback. |
| Jira Agent | Not present in current tree | `8001` per README/run script | Expected `GET /tickets/{issue_key}` | Fetches and normalizes Jira ticket data. The orchestrator depends on this service through `JIRA_SERVICE_URL`. |
| Reviewer Agent | `agents/reviewer_agent.py` | `8002` | `POST /review` | Reviews proposed changes against the Jira ticket and returns structured feedback. |
| Orchestrator Agent | `agents/orchestrator_agent.py` | `8010` in `run_all.ps1`; `8003` in README | `/api/workflow/*`, `/ws/workflow` | Coordinates the full workflow and exposes dashboard control APIs. |
| Repo Agent | `agents/repo_agent.py` | `8004` | `/prepare-repo`, `/create-branch`, `/read-files`, `/apply-changes`, `/diff`, `/commit`, `/push`, `/open-pr` | Handles repository preparation, branch operations, file reads, file updates, and pull request creation. |
| Knowledge Agent | `agents/knowledge_agent.py` | `8005` | `/ensure-knowledge`, `/build-knowledge`, `/update-knowledge`, `/load-knowledge`, `/sync-branches` | Builds and maintains branch-scoped repository knowledge summaries. |
| Planner Agent | `agents/planner_agent.py` | `8006` | `POST /plan` | Produces structured implementation plans from Jira tickets and repository knowledge. |
| Model Selector Agent | `agents/model_selector_agent.py` | `8007` | `POST /select-models` | Selects suitable LLMs for knowledge, planning, development, and review roles. |
| Angular Dashboard | `dashboard/` | `4200` | Calls `/api/workflow/*` | Provides monitoring, manual control, model selection, message editing, and workflow visualization. |

### 5.2 Communication Flow

The main workflow is implemented in `ManualWorkflowController` inside `agents/orchestrator_agent.py`. It runs the following sequence:

1. `_run_jira`: prepares the repository for pre-sync in Git mode, calls Knowledge `/sync-branches`, then fetches the Jira ticket from `GET {JIRA_SERVICE_URL}/tickets/{issue_key}`.
2. `_run_model_selector`: optionally calls the Model Selector Agent when automatic model selection is enabled.
3. `_run_repo_initial`: calls Repo `/prepare-repo`, then creates a new branch with `/create-branch` or uses an existing/local branch.
4. `_run_knowledge`: calls Knowledge `/ensure-knowledge` for the selected branch.
5. `_run_planner`: calls Planner `/plan` with the Jira ticket and project knowledge.
6. `_run_developer`: reads planner-selected files through Repo `/read-files`, then calls Developer `/generate`.
7. `_run_reviewer`: builds a unified diff with `build_review_diff` and calls Reviewer `/review`.
8. `_run_developer_improve`: if review feedback contains blocking issues, calls Developer `/improve`.
9. `_run_repo_final`: calls Repo `/apply-changes`, Knowledge `/update-knowledge`, and optionally Repo `/open-pr`.

The dashboard communicates with the orchestrator using:

- HTTP endpoints under `/api/workflow/*`.
- WebSocket updates from `/ws/workflow`.
- A polling fallback through `WorkflowStateService.pollFallback()` if WebSocket connection fails.

## 6. Work Carried Out

### 6.1 Shared Configuration and Schemas

The shared configuration layer is implemented in `shared/config.py`. It loads environment variables with `load_dotenv()`, defines service URLs, provider keys, repository paths, Jira credentials, and model defaults. The function `check_config()` verifies that at least one configured model provider API key exists, while `check_jira_config()` validates Jira credentials.

The shared data contracts are implemented in `shared/schemas.py`. Important models include:

- `GenerateRequest` for workflow start parameters.
- `JiraTicket` for normalized ticket metadata.
- `PlanningRequest` and `PlanningResult` for planning.
- `AgentTaskRequest`, `DeveloperOutput`, `FileChange`, and `RepoFile` for development tasks.
- `ReviewFeedback` and `ReviewIssue` for review results.
- Repository operation models such as `PrepareRepoRequest`, `CreateBranchRequest`, `ReadFilesRequest`, `ApplyChangesRequest`, `PullRequestRequest`, and their responses.

Several defensive validators were implemented. `GenerateRequest.validate_branch_exclusivity()` prevents simultaneous use of `base_branch` and `existing_branch`. `PlanningResult.normalize_legacy_file_fields()` accepts legacy `likely_files`, converts plain strings into arrays for list fields, and ensures `new_files` exists. `DeveloperOutput.validate_changes()` rejects empty content for create/update/upsert operations. `ReviewFeedback.normalize_list_fields()` similarly normalizes list-like fields returned by different models.

### 6.2 Repository Agent

`agents/repo_agent.py` encapsulates Git and GitHub operations. It can prepare a repository by cloning or fetching it in GitHub mode through `prepare_repo()`, or validate an existing local Git folder through `local_repo_path()`.

The agent creates branches using GitHub refs in `create_branch()`. Branch names are generated by `build_branch_name(issue_key, title)` and made unique with `unique_github_branch_name()`. File updates are applied through GitHub's Contents API in `apply_changes()`, using `github_put_file_with_retry()` to handle SHA conflicts by refetching the file and retrying after a `409` conflict.

The function `checkout_branch()` includes a key design decision: after checking out a branch, it fetches and hard-resets the local working tree to `origin/<branch>`. This compensates for the fact that changes are committed through the GitHub Contents API rather than local `git commit` and `git push`, so the local clone could otherwise become stale.

Path safety is handled by `safe_repo_file()`, which rejects absolute paths and paths that escape the repository root. In local mode, `apply_changes()` writes directly to the local working tree and does not create commits or pull requests.

### 6.3 Knowledge Agent

`agents/knowledge_agent.py` builds a branch-scoped knowledge base for a repository. It scans source files with extensions such as `.py`, `.js`, `.ts`, `.tsx`, `.md`, `.yaml`, `.yml`, and `.json`, while ignoring directories such as `.git`, `node_modules`, `dist`, `build`, `.venv`, and cache directories.

For each source file, `_summarize_file()` uses LiteLLM to produce a structured JSON summary containing the path, purpose, Markdown summary, classes, functions, imports, exports, and metadata. If model summarization fails, the function falls back to a simple extractor that scans imports, functions, and classes directly from the file content.

The agent stores knowledge under a branch-specific directory and records metadata including `source_sha`. The methods `_refresh_if_drifted()`, `ensure_knowledge()`, `update_knowledge()`, and `sync_all_branches()` keep knowledge synchronized with Git history. An important design choice is reading changed file content from Git object storage with `git show <sha>:<path>` through `_read_file_at_commit()`, instead of trusting the local working tree. This matches the Repo Agent's GitHub Contents API write strategy.

The current file references `hashlib.sha1()` in `_local_repo_id()` but does not import `hashlib`. This should be fixed before using local-mode knowledge paths that call this function.

### 6.4 Planner Agent

`agents/planner_agent.py` implements `PlannerAgent.plan_task()`, exposed through `POST /plan`. It receives a `JiraTicket` and project knowledge, then asks an LLM to produce a strict JSON `PlanningResult`.

A significant part of the planner prompt is dedicated to path correctness. It tells the model that the known file list is the ground truth and explicitly prevents invented framework paths such as `app/main.py` when the actual repository does not use an `app/` directory. After the LLM response, the agent normalizes path separators, drops unknown existing files, corrects some invented top-level directories for new files, and defaults missing complexity to `"Medium"`.

This design addresses a common LLM failure mode: generating plausible but incorrect file paths based on generic framework conventions instead of the actual repository layout.

### 6.5 Developer Agent

`agents/developer_agent.py` implements code generation and revision. `generate_code()` builds a prompt from the task, original Jira ticket, planning result, planned new files, and actual file contents read by the Repo Agent. `improve_code()` builds a second prompt using the original implementation and structured review feedback.

The Developer Agent returns a `DeveloperOutput` with:

- `explanation`
- `changes`
- `code`

Each `FileChange` must include a path, an action, and full content for create/update/upsert actions. The prompt explicitly requires full file contents after the edit, not summaries. The helper `format_file_boundary_rule()` limits updates to files that were actually provided as context, while allowing creation of new files. This reduces the risk of rewriting an existing file whose content was not read.

### 6.6 Reviewer Agent

`agents/reviewer_agent.py` implements `ReviewerAgent.review_code()`, exposed through `POST /review`. It reviews the proposed diff, ticket data, developer explanation, and relevant repository files. The prompt asks the model to separate blocking issues from optional suggestions and to prioritize missing requirements, functional bugs, security issues, and performance regressions.

The response is validated as `ReviewFeedback`. The orchestrator then uses `requires_revision` and `blocking_issues` to decide whether `_run_developer_improve()` should call the Developer Agent again.

### 6.7 Model Selection

`shared/available_models.py` defines a static registry of available LLMs. Each entry includes:

- LiteLLM model id
- display label
- provider
- required environment variable
- capability description
- power score

`model_selection.json` stores the current per-agent model choices for `knowledge`, `planner`, `developer`, `reviewer`, and `model_selector`.

The orchestrator exposes model-selection endpoints:

- `GET /api/workflow/available-models`
- `GET /api/workflow/model-selection`
- `POST /api/workflow/model-selection`
- `GET /api/workflow/auto-model-selection`
- `POST /api/workflow/set-auto-model-selection`

The Model Selector Agent in `agents/model_selector_agent.py` performs health checks with a small LiteLLM prompt, filters unhealthy candidates, resolves the fixed selector model from `model_selection.json`, classifies ticket complexity, and returns a model assignment for the four main LLM roles. The orchestrator also performs candidate health checks before calling the selector.

### 6.8 Orchestrator and Manual Control

`agents/orchestrator_agent.py` is the central coordination service. It maintains workflow state in `ManualWorkflowController`, including the current step, current agent, next agent, messages, active path, context, execution status, and connected WebSocket clients.

The orchestrator supports manual and automatic execution:

- Manual mode: the dashboard starts the workflow, then the operator advances one agent at a time through `POST /api/workflow/run-next-agent`.
- Automatic mode: `_run_automatic_workflow()` executes the full sequence without waiting for approval between agents.

The orchestrator also supports pausing, resuming, stopping, restarting, skipping an agent, rerunning the current agent, exporting logs, saving edited messages, and sending edited messages. Message editing is implemented through `save_edited_message()` and `send_edited_message()`, and `_current_planning_result()` reads the edited Planner-to-Developer payload if one exists.

The function `validate_planned_changes()` adds a safety boundary by rejecting Developer outputs that attempt to update/delete/upsert existing files outside the files selected by the Planner and read by the Repo Agent.

### 6.9 Angular Dashboard

The dashboard in `dashboard/` provides a visual operator interface.

Main parts:

- `WorkflowStateService` centralizes HTTP calls, WebSocket connection, polling fallback, local workflow state, model-selection state, and command dispatch.
- `ControlCenterComponent` is the main page for the mission-control view.
- `GlobalControlBarComponent` provides ticket, branch, repo URL, local folder path, workspace mode, manual/automatic mode, open PR option, start/stop/restart, and export log controls.
- `PipelineGraphComponent` uses Cytoscape to visualize the workflow pipeline.
- `AgentInspectorComponent` displays selected agent status, output, files, and errors.
- `ApprovalPanelComponent` exposes manual execution controls.
- `ModelSelectionPanelComponent` displays and saves model selections for each role.
- `CommunicationCenterComponent`, `MessageEditorComponent`, `StructuredJsonEditorComponent`, and `JsonViewerComponent` provide inspection and editing of messages exchanged between agents.

The dashboard routes are defined in `dashboard/src/app/app.routes.ts`: the root path displays the control center, and `/communications` displays the communication center.

## 7. Results

Based on the current codebase, the following features are implemented:

- A FastAPI-based multi-agent architecture with dedicated services for repository operations, knowledge management, planning, development, review, model selection, and orchestration.
- Shared Pydantic schemas for typed communication between agents.
- HTTP-based orchestration through `httpx.AsyncClient`.
- Manual and automatic workflow execution modes.
- Dashboard APIs under `/api/workflow/*`.
- WebSocket state broadcasting through `/ws/workflow`.
- Angular dashboard with control center, pipeline graph, agent inspector, model selection, communication center, JSON viewer, and editable message payloads.
- GitHub branch creation, file updates/deletes through the Contents API, and pull request creation.
- Local-folder mode for applying changes directly to a local Git working tree.
- Branch-scoped repository knowledge generation and incremental updates.
- LLM-backed planning, code generation, code review, knowledge summarization, and model selection.
- Defensive handling for schema drift in model outputs, especially list fields and file path formats.
- Model health checks and credential-based filtering of available model options.

Current limitations and points to verify:

- The Jira Agent implementation is not present in the current repository, although the orchestrator and README expect a Jira service.
- The current file layout uses `agents/` and `shared/`, while imports and `run_all.ps1` still reference bare module names such as `config`, `schemas`, and `developer_agent`. Running the services may require adjusting `PYTHONPATH`, working directories, or module paths.
- The orchestrator port differs between README (`8003`) and dashboard/run script (`8010`).
- `agents/knowledge_agent.py` references `hashlib` without importing it.
- In local-folder mode, `agents/orchestrator_agent.py` sends `"workspace_mode": self.workspace_mode` to Knowledge endpoints, while `agents/knowledge_agent.py` reads `payload.get("local", False)`. This means Knowledge local-mode storage may not be activated unless the payload key is aligned.

## 8. Skills and Lessons Learned

[FILL IN: technical skills acquired, such as FastAPI, Angular, GitHub API, Jira integration, prompt engineering, multi-agent design, schema validation, and debugging distributed services.]

[FILL IN: soft skills acquired, such as autonomy, communication with supervisors, technical documentation, requirement analysis, and iterative delivery.]

[FILL IN: personal reflection on challenges encountered and how they were solved.]

## 9. Conclusion

[FILL IN: summary of the internship, achieved objectives, value of the project for the company/team, remaining work, and possible future improvements.]

## 10. Appendices

### Appendix A - Developer Agent Endpoints

File: `agents/developer_agent.py`

| Method | Endpoint | Function | Response model |
|---|---|---|---|
| POST | `/generate` | `generate_code()` | `DeveloperOutput` |
| POST | `/improve` | `improve_code()` | `AgentMessage` |

### Appendix B - Reviewer Agent Endpoints

File: `agents/reviewer_agent.py`

| Method | Endpoint | Function | Response model |
|---|---|---|---|
| POST | `/review` | `review()` | `AgentMessage` |

### Appendix C - Planner Agent Endpoints

File: `agents/planner_agent.py`

| Method | Endpoint | Function | Response model |
|---|---|---|---|
| POST | `/plan` | `plan()` | `PlanningResult` |

### Appendix D - Repo Agent Endpoints

File: `agents/repo_agent.py`

| Method | Endpoint | Function | Response model |
|---|---|---|---|
| POST | `/prepare-repo` | `prepare_repo()` | `RepoInfo` |
| POST | `/create-branch` | `create_branch()` | `BranchResponse` |
| POST | `/read-files` | `read_files()` | `ReadFilesResponse` |
| POST | `/apply-changes` | `apply_changes()` | `ApplyChangesResponse` |
| POST | `/diff` | `diff()` | `RepoDiffResponse` |
| POST | `/commit` | `commit()` | `CommitResponse` |
| POST | `/push` | `push()` | `PushResponse` |
| POST | `/open-pr` | `open_pr()` | `PullRequestResponse` |

### Appendix E - Knowledge Agent Endpoints

File: `agents/knowledge_agent.py`

| Method | Endpoint | Function | Response |
|---|---|---|---|
| POST | `/ensure-knowledge` | `ensure_knowledge_endpoint()` | Repository knowledge dictionary |
| POST | `/build-knowledge` | `build_knowledge_endpoint()` | Metadata dictionary |
| POST | `/update-knowledge` | `update_knowledge_endpoint()` | Update summary dictionary |
| GET | `/load-knowledge` | `load_knowledge_endpoint()` | Repository knowledge dictionary |
| POST | `/sync-branches` | `sync_branches_endpoint()` | Branch sync summary dictionary |

### Appendix F - Model Selector Agent Endpoints

File: `agents/model_selector_agent.py`

| Method | Endpoint | Function | Response |
|---|---|---|---|
| POST | `/select-models` | `select_models()` | Model selection dictionary |

### Appendix G - Orchestrator Agent Endpoints

File: `agents/orchestrator_agent.py`

| Method | Endpoint | Function | Purpose |
|---|---|---|---|
| GET | `/api/workflow/state` | `workflow_state()` | Return dashboard workflow snapshot. |
| WS | `/ws/workflow` | `workflow_socket()` | Push workflow snapshots over WebSocket. |
| POST | `/api/workflow/set-mode` | `workflow_set_mode()` | Switch between manual and automatic mode. |
| GET | `/api/workflow/mode` | `workflow_get_mode()` | Return current workflow mode. |
| POST | `/api/workflow/start` | `workflow_start()` | Reset and start a workflow. |
| POST | `/api/workflow/run-next-agent` | `workflow_run_next()` | Execute the next agent in manual mode. |
| POST | `/api/workflow/pause` | `workflow_pause()` | Pause the workflow. |
| POST | `/api/workflow/resume` | `workflow_resume()` | Resume the workflow. |
| POST | `/api/workflow/stop` | `workflow_stop()` | Stop the workflow. |
| POST | `/api/workflow/restart` | `workflow_restart()` | Reset workflow state and restart parameters. |
| POST | `/api/workflow/rerun-current-agent` | `workflow_rerun_current()` | Re-run the current workflow step. |
| POST | `/api/workflow/skip-agent` | `workflow_skip_agent()` | Skip the current workflow step. |
| POST | `/api/workflow/cancel` | `workflow_cancel()` | Cancel the workflow. |
| POST | `/api/workflow/export-log` | `workflow_export_log()` | Return the current execution snapshot. |
| POST | `/api/workflow/save-edited-message` | `workflow_save_edited_message()` | Save an edited message payload. |
| POST | `/api/workflow/send-edited-message` | `workflow_send_edited_message()` | Mark an edited message as sent. |
| GET | `/api/workflow/available-models` | `workflow_available_models()` | Return credentialed models from `AVAILABLE_MODELS`. |
| GET | `/api/workflow/model-selection` | `workflow_get_model_selection()` | Return persisted per-agent model selections. |
| POST | `/api/workflow/model-selection` | `workflow_set_model_selection()` | Update per-agent model selections. |
| GET | `/api/workflow/auto-model-selection` | `workflow_get_auto_model_selection()` | Return automatic model-selection status. |
| POST | `/api/workflow/set-auto-model-selection` | `workflow_set_auto_model_selection()` | Enable or disable automatic model selection. |

### Appendix H - Git History Summary

The visible git history indicates the project evolved through several phases:

| Date | Commit(s) | Observed evolution |
|---|---|---|
| 2026-07-15 to 2026-07-16 | `e6fc92c`, `d6fcbb6`, `640652f`, `f840658`, `3ea02ef`, `0f3f0cd`, `b3e08e3` | Early dashboard work, message editing, pipeline updates, automatic/manual mode, branch/PR options, and repository input options. |
| 2026-07-18 to 2026-07-20 | `6839a89`, `2cd4a02`, `6fcd2ae`, `afa2d1a`, `653d6ba`, `f759977` | Fixes around existing files and knowledge, testing branch merge, Angular dashboard consolidation, and removal of older visualization/dashboard directories. |
| 2026-07-25 to 2026-08-01 | `319e1a6`, `df599b6`, `49d2726`, `263077b`, `be04aec` | Main branch initialization for the current project line, repository changes, and automatic workflow progress. |
| 2026-08-03 to 2026-08-15 | `d159a08`, `9239a07`, `cc4f9d6`, `4921612`, `3a410e0`, `bb43361`, `ed4d7dc`, `e1a46fe`, `ff04936` | Model-governor/model-selection branch work, local-folder mode, knowledge placement fixes, README/setup updates, run script addition, and merge of the model-governor branch. |
| 2026-08-17 | `e8536af` | File organization into the current `agents/`, `shared/`, and `dashboard/` structure. |
