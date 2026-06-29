import logging
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException

from config import GITHUB_REPO_URL, GITHUB_TOKEN, REPO_WORKSPACE_ROOT, configure_logging
from schemas import (
    ApplyChangesRequest,
    ApplyChangesResponse,
    BranchResponse,
    CommitRequest,
    CommitResponse,
    CreateBranchRequest,
    PrepareRepoRequest,
    PullRequestRequest,
    PullRequestResponse,
    PushRequest,
    PushResponse,
    ReadFilesRequest,
    ReadFilesResponse,
    RepoDiffRequest,
    RepoDiffResponse,
    RepoFile,
    RepoInfo,
)

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Repo Agent Service", version="1.0.0")


def run_git(repo_path: Path, args: list[str]) -> str:
    command = ["git", *args]
    logger.info("Running git command: %s", " ".join(command))
    result = subprocess.run(
        command,
        cwd=repo_path,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(message or f"Git command failed: {' '.join(command)}")
    return result.stdout.strip()


def ensure_workspace_root() -> Path:
    REPO_WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    return REPO_WORKSPACE_ROOT.resolve()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "repo"


def repo_id_from_url(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    if parsed.scheme:
        path = parsed.path
    elif ":" in repo_url:
        path = repo_url.split(":", 1)[1]
    else:
        path = repo_url

    path = path.removesuffix(".git").strip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2:
        return slugify(f"{parts[-2]}-{parts[-1]}")
    return slugify(parts[-1] if parts else repo_url)


def github_owner_repo(remote_url: str) -> tuple[str, str]:
    parsed = urlparse(remote_url)
    if parsed.scheme and "github.com" in parsed.netloc:
        path = parsed.path
    elif remote_url.startswith("git@github.com:"):
        path = remote_url.split(":", 1)[1]
    else:
        raise ValueError("Only GitHub remotes are supported for opening pull requests.")

    path = path.removesuffix(".git").strip("/")
    parts = path.split("/")
    if len(parts) != 2:
        raise ValueError("Could not parse GitHub owner and repo from remote URL.")
    return parts[0], parts[1]


def repo_path_for(repo_id: str) -> Path:
    root = ensure_workspace_root()
    repo_path = (root / slugify(repo_id)).resolve()
    if root != repo_path and root not in repo_path.parents:
        raise ValueError("Repo path escapes workspace root.")
    return repo_path


def existing_repo_path(repo_id: str) -> Path:
    repo_path = repo_path_for(repo_id)
    if not (repo_path / ".git").exists():
        raise ValueError(f"Repo is not prepared yet: {repo_id}")
    return repo_path


def safe_repo_file(repo_path: Path, relative_path: str) -> Path:
    if Path(relative_path).is_absolute():
        raise ValueError(f"Absolute paths are not allowed: {relative_path}")

    file_path = (repo_path / relative_path).resolve()
    if repo_path != file_path and repo_path not in file_path.parents:
        raise ValueError(f"Path escapes repo: {relative_path}")
    return file_path


def current_branch(repo_path: Path) -> str | None:
    branch = run_git(repo_path, ["branch", "--show-current"])
    return branch or None


def ensure_clean_worktree(repo_path: Path) -> None:
    status = run_git(repo_path, ["status", "--porcelain"])
    if status:
        raise ValueError("Repo has uncommitted changes. Commit or discard them first.")


def ensure_not_protected_branch(repo_path: Path) -> None:
    branch = current_branch(repo_path)
    if not branch:
        raise ValueError("Refusing to modify repo without an active branch.")
    if branch in {"main", "master"}:
        raise ValueError("Refusing to modify protected branch. Create a ticket branch first.")


def build_branch_name(issue_key: str, title: str) -> str:
    title_slug = slugify(title)
    return f"agent/{issue_key.upper()}-{title_slug}"[:80].rstrip("-")


def branch_exists(repo_path: Path, branch: str) -> bool:
    try:
        run_git(repo_path, ["rev-parse", "--verify", f"refs/heads/{branch}"])
        return True
    except RuntimeError:
        return False


def unique_branch_name(repo_path: Path, branch: str) -> str:
    if not branch_exists(repo_path, branch):
        return branch

    for index in range(2, 100):
        candidate = f"{branch}-{index}"
        if not branch_exists(repo_path, candidate):
            return candidate

    raise ValueError(f"Could not create a unique branch name for {branch}")


def build_commit_message(issue_key: str, summary: str, body: str | None) -> str:
    clean_summary = re.sub(r"\s+", " ", summary).strip().rstrip(".")
    if not clean_summary:
        clean_summary = "update project"

    subject = f"{issue_key.upper()} {clean_summary[0].lower()}{clean_summary[1:]}"
    subject = subject[:72].rstrip()
    if not body:
        return subject
    return f"{subject}\n\n{body.strip()}"


def build_pr_body(request: PullRequestRequest) -> str:
    sections = [
        "## Summary",
        request.summary,
        "",
        "## Ticket",
        request.ticket_url or request.issue_key,
    ]

    if request.test_results:
        sections.extend(["", "## Tests", request.test_results])

    sections.extend(
        [
            "",
            "## Notes",
            "This pull request was created by the Repo Agent and is not auto-merged.",
        ]
    )
    return "\n".join(sections)


@app.post("/prepare-repo", response_model=RepoInfo)
def prepare_repo(request: PrepareRepoRequest) -> RepoInfo:
    try:
        repo_url = request.repo_url or GITHUB_REPO_URL
        if not repo_url:
            raise ValueError(
                "Missing repo_url. Pass it in the request or set GITHUB_REPO_URL in .env."
            )

        repo_id = request.repo_id or repo_id_from_url(repo_url)
        repo_path = repo_path_for(repo_id)

        if repo_path.exists():
            if not (repo_path / ".git").exists():
                raise ValueError(f"Workspace path exists but is not a git repo: {repo_path}")
            run_git(repo_path, ["fetch", "--all", "--prune"])
            status = "updated"
        else:
            ensure_workspace_root()
            subprocess.run(
                ["git", "clone", repo_url, str(repo_path)],
                text=True,
                capture_output=True,
                check=True,
            )
            status = "cloned"

        remote_url = run_git(repo_path, ["remote", "get-url", "origin"])
        return RepoInfo(
            repo_id=repo_id,
            path=str(repo_path),
            current_branch=current_branch(repo_path),
            remote_url=remote_url,
            status=status,
        )
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip()
        logger.warning("Repo clone failed: %s", message)
        raise HTTPException(status_code=502, detail=message or "Repo clone failed.") from exc
    except ValueError as exc:
        logger.warning("Repo prepare validation failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Repo prepare failed")
        raise HTTPException(status_code=500, detail="Repo prepare failed.") from exc


@app.post("/create-branch", response_model=BranchResponse)
def create_branch(request: CreateBranchRequest) -> BranchResponse:
    try:
        repo_path = existing_repo_path(request.repo_id)
        ensure_clean_worktree(repo_path)

        branch = unique_branch_name(
            repo_path,
            build_branch_name(request.issue_key, request.title),
        )
        run_git(repo_path, ["fetch", "origin", request.base_branch])
        run_git(repo_path, ["checkout", "-B", request.base_branch, f"origin/{request.base_branch}"])
        run_git(repo_path, ["checkout", "-b", branch])

        return BranchResponse(
            repo_id=request.repo_id,
            branch=branch,
            base_branch=request.base_branch,
        )
    except ValueError as exc:
        logger.warning("Branch creation validation failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Branch creation failed")
        raise HTTPException(status_code=500, detail="Branch creation failed.") from exc


@app.post("/read-files", response_model=ReadFilesResponse)
def read_files(request: ReadFilesRequest) -> ReadFilesResponse:
    try:
        repo_path = existing_repo_path(request.repo_id)
        files = []

        for path in request.paths:
            file_path = safe_repo_file(repo_path, path)
            if not file_path.is_file():
                raise ValueError(f"File does not exist: {path}")
            files.append(RepoFile(path=path, content=file_path.read_text(encoding="utf-8")))

        return ReadFilesResponse(repo_id=request.repo_id, files=files)
    except ValueError as exc:
        logger.warning("Read files validation failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnicodeDecodeError as exc:
        logger.warning("Read files failed for non-text file: %s", exc)
        raise HTTPException(status_code=400, detail="Only UTF-8 text files are supported.") from exc
    except Exception as exc:
        logger.exception("Read files failed")
        raise HTTPException(status_code=500, detail="Read files failed.") from exc


@app.post("/apply-changes", response_model=ApplyChangesResponse)
def apply_changes(request: ApplyChangesRequest) -> ApplyChangesResponse:
    try:
        repo_path = existing_repo_path(request.repo_id)
        ensure_not_protected_branch(repo_path)
        changed_files = []

        for change in request.changes:
            file_path = safe_repo_file(repo_path, change.path)
            action = change.action.lower()

            if action in {"create", "update", "upsert"}:
                if change.content is None:
                    raise ValueError(f"Missing content for {change.path}")
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(change.content, encoding="utf-8")
            elif action == "delete":
                if file_path.exists():
                    file_path.unlink()
            else:
                raise ValueError(f"Unsupported change action: {change.action}")

            changed_files.append(change.path)

        return ApplyChangesResponse(repo_id=request.repo_id, changed_files=changed_files)
    except ValueError as exc:
        logger.warning("Apply changes validation failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Apply changes failed")
        raise HTTPException(status_code=500, detail="Apply changes failed.") from exc


@app.post("/diff", response_model=RepoDiffResponse)
def diff(request: RepoDiffRequest) -> RepoDiffResponse:
    try:
        repo_path = existing_repo_path(request.repo_id)
        repo_diff = run_git(repo_path, ["diff", "--", "."])
        return RepoDiffResponse(repo_id=request.repo_id, diff=repo_diff)
    except Exception as exc:
        logger.exception("Repo diff failed")
        raise HTTPException(status_code=500, detail="Repo diff failed.") from exc


@app.post("/commit", response_model=CommitResponse)
def commit(request: CommitRequest) -> CommitResponse:
    try:
        repo_path = existing_repo_path(request.repo_id)
        ensure_not_protected_branch(repo_path)
        status = run_git(repo_path, ["status", "--porcelain"])
        if not status:
            raise ValueError("No changes to commit.")

        message = build_commit_message(request.issue_key, request.summary, request.body)
        run_git(repo_path, ["add", "--all"])
        run_git(repo_path, ["commit", "-m", message])
        commit_sha = run_git(repo_path, ["rev-parse", "HEAD"])

        return CommitResponse(
            repo_id=request.repo_id,
            commit_sha=commit_sha,
            message=message,
        )
    except ValueError as exc:
        logger.warning("Commit validation failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Commit failed")
        raise HTTPException(status_code=500, detail="Commit failed.") from exc


@app.post("/push", response_model=PushResponse)
def push(request: PushRequest) -> PushResponse:
    try:
        repo_path = existing_repo_path(request.repo_id)
        branch = request.branch or current_branch(repo_path)
        if not branch:
            raise ValueError("Could not determine current branch.")
        if branch in {"main", "master"}:
            raise ValueError("Refusing to push protected branch.")

        run_git(repo_path, ["push", "-u", "origin", branch])
        return PushResponse(repo_id=request.repo_id, branch=branch)
    except ValueError as exc:
        logger.warning("Push validation failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Push failed")
        raise HTTPException(status_code=500, detail="Push failed.") from exc


@app.post("/open-pr", response_model=PullRequestResponse)
async def open_pr(request: PullRequestRequest) -> PullRequestResponse:
    try:
        if not GITHUB_TOKEN:
            raise ValueError("Missing GITHUB_TOKEN. Add it to your .env file.")

        repo_path = existing_repo_path(request.repo_id)
        head_branch = request.head_branch or current_branch(repo_path)
        if not head_branch:
            raise ValueError("Could not determine PR head branch.")
        if head_branch in {"main", "master"}:
            raise ValueError("Refusing to open a PR from a protected branch.")

        remote_url = run_git(repo_path, ["remote", "get-url", "origin"])
        owner, repo = github_owner_repo(remote_url)
        pr_title = f"{request.issue_key.upper()} {request.title.strip()}"
        payload = {
            "title": pr_title[:256],
            "head": head_branch,
            "base": request.base_branch,
            "body": build_pr_body(request),
            "draft": request.draft,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {GITHUB_TOKEN}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=payload,
            )
            response.raise_for_status()

        data = response.json()
        return PullRequestResponse(
            repo_id=request.repo_id,
            number=data["number"],
            url=data["html_url"],
            title=data["title"],
        )
    except httpx.HTTPStatusError as exc:
        logger.warning("GitHub PR request failed: %s", exc)
        raise HTTPException(status_code=502, detail="GitHub PR request failed.") from exc
    except ValueError as exc:
        logger.warning("Open PR validation failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Open PR failed")
        raise HTTPException(status_code=500, detail="Open PR failed.") from exc
