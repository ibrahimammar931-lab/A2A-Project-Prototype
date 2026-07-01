import logging
import re
import subprocess
from base64 import b64encode
from pathlib import Path
from urllib.parse import quote, urlparse

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


def github_headers() -> dict[str, str]:
    if not GITHUB_TOKEN:
        raise ValueError("Missing GITHUB_TOKEN. Add it to your .env file.")
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_api_url(owner: str, repo: str, path: str) -> str:
    return f"https://api.github.com/repos/{owner}/{repo}{path}"


def github_get_ref(owner: str, repo: str, branch: str) -> dict:
    branch_path = quote(f"heads/{branch}", safe="/")
    response = httpx.get(
        github_api_url(owner, repo, f"/git/ref/{branch_path}"),
        headers=github_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def github_branch_exists(owner: str, repo: str, branch: str) -> bool:
    try:
        github_get_ref(owner, repo, branch)
        return True
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return False
        raise


def unique_github_branch_name(owner: str, repo: str, branch: str) -> str:
    if not github_branch_exists(owner, repo, branch):
        return branch

    for index in range(2, 100):
        candidate = f"{branch}-{index}"
        if not github_branch_exists(owner, repo, candidate):
            return candidate

    raise ValueError(f"Could not create a unique branch name for {branch}")


def github_get_file(owner: str, repo: str, path: str, branch: str) -> dict | None:
    file_path = quote(path, safe="/")
    response = httpx.get(
        github_api_url(owner, repo, f"/contents/{file_path}"),
        headers=github_headers(),
        params={"ref": branch},
        timeout=30,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        raise ValueError(f"Path is a directory, not a file: {path}")
    return data


def github_put_file(
    owner: str,
    repo: str,
    path: str,
    branch: str,
    message: str,
    content: str,
    sha: str | None = None,
) -> str:
    file_path = quote(path, safe="/")
    payload = {
        "message": message,
        "content": b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    response = httpx.put(
        github_api_url(owner, repo, f"/contents/{file_path}"),
        headers=github_headers(),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["commit"]["sha"]


def github_put_file_with_retry(
    owner: str,
    repo: str,
    path: str,
    branch: str,
    message: str,
    content: str,
) -> str:
    existing_file = github_get_file(owner, repo, path, branch)
    try:
        return github_put_file(
            owner=owner,
            repo=repo,
            path=path,
            branch=branch,
            message=message,
            content=content,
            sha=existing_file["sha"] if existing_file else None,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 409:
            raise

        logger.warning("GitHub SHA conflict for %s; refetching and retrying", path)
        existing_file = github_get_file(owner, repo, path, branch)
        return github_put_file(
            owner=owner,
            repo=repo,
            path=path,
            branch=branch,
            message=message,
            content=content,
            sha=existing_file["sha"] if existing_file else None,
        )


def github_delete_file(
    owner: str,
    repo: str,
    path: str,
    branch: str,
    message: str,
    sha: str,
) -> str:
    file_path = quote(path, safe="/")
    response = httpx.request(
        "DELETE",
        github_api_url(owner, repo, f"/contents/{file_path}"),
        headers=github_headers(),
        json={
            "message": message,
            "sha": sha,
            "branch": branch,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["commit"]["sha"]


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


def normalize_change_action(action: str) -> str:
    action = action.lower().strip()
    action_aliases = {
        "add": "upsert",
        "added": "upsert",
        "create": "upsert",
        "created": "upsert",
        "modify": "upsert",
        "modified": "upsert",
        "update": "upsert",
        "updated": "upsert",
        "refactor": "upsert",
        "refactored": "upsert",
        "replace": "upsert",
        "replaced": "upsert",
        "write": "upsert",
        "written": "upsert",
        "remove": "delete",
        "removed": "delete",
        "delete": "delete",
        "deleted": "delete",
    }
    return action_aliases.get(action, action)


@app.post("/prepare-repo", response_model=RepoInfo)
def prepare_repo(request: PrepareRepoRequest) -> RepoInfo:
    try:
        repo_url = request.repo_url or GITHUB_REPO_URL
        if not repo_url:
            raise ValueError(
                "Missing repo_url. Pass it in the request or set GITHUB_REPO_URL in .env."
            )

        repo_id = repo_id_from_url(repo_url)
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
        repo_id = repo_id_from_url(request.repo_url)
        owner, repo = github_owner_repo(request.repo_url)

        branch = build_branch_name(request.issue_key, request.title)
        branch = unique_github_branch_name(owner, repo, branch)
        base_ref = github_get_ref(owner, repo, request.base_branch)
        base_sha = base_ref["object"]["sha"]
        response = httpx.post(
            github_api_url(owner, repo, "/git/refs"),
            headers=github_headers(),
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
            timeout=30,
        )
        response.raise_for_status()

        return BranchResponse(
            repo_id=repo_id,
            branch=branch,
            base_branch=request.base_branch,
        )
    except ValueError as exc:
        logger.warning("Branch creation validation failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        logger.warning("GitHub branch creation failed: %s", exc.response.text)
        raise HTTPException(status_code=502, detail=exc.response.text) from exc
    except Exception as exc:
        logger.exception("Branch creation failed")
        raise HTTPException(status_code=500, detail="Branch creation failed.") from exc


@app.post("/read-files", response_model=ReadFilesResponse)
def read_files(request: ReadFilesRequest) -> ReadFilesResponse:
    try:
        repo_id = repo_id_from_url(request.repo_url)
        repo_path = existing_repo_path(repo_id)
        files = []

        for path in request.paths:
            file_path = safe_repo_file(repo_path, path)
            if not file_path.is_file():
                raise ValueError(f"File does not exist: {path}")
            files.append(RepoFile(path=path, content=file_path.read_text(encoding="utf-8")))

        return ReadFilesResponse(repo_id=repo_id, files=files)
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
        repo_id = repo_id_from_url(request.repo_url)
        owner, repo = github_owner_repo(request.repo_url)
        branch = request.branch
        if not branch:
            raise ValueError("Missing branch for GitHub API apply-changes.")

        changed_files = []
        commit_shas = []

        for change in request.changes:
            action = normalize_change_action(change.action)
            message = request.commit_message or f"Update {change.path}"

            if action in {"create", "update", "upsert"}:
                if change.content is None:
                    raise ValueError(f"Missing content for {change.path}")
                commit_sha = github_put_file_with_retry(
                    owner=owner,
                    repo=repo,
                    path=change.path,
                    branch=branch,
                    message=message,
                    content=change.content,
                )
                commit_shas.append(commit_sha)
            elif action == "delete":
                existing_file = github_get_file(owner, repo, change.path, branch)
                if existing_file:
                    commit_sha = github_delete_file(
                        owner=owner,
                        repo=repo,
                        path=change.path,
                        branch=branch,
                        message=message,
                        sha=existing_file["sha"],
                    )
                    commit_shas.append(commit_sha)
            else:
                raise ValueError(f"Unsupported change action: {change.action}")

            changed_files.append(change.path)

        return ApplyChangesResponse(
            repo_id=repo_id,
            changed_files=changed_files,
            branch=branch,
            commit_shas=commit_shas,
        )
    except ValueError as exc:
        logger.warning("Apply changes validation failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=f"{str(exc)}; request={request.model_dump_json()}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        logger.warning("GitHub apply changes failed: %s", exc.response.text)
        raise HTTPException(status_code=502, detail=exc.response.text) from exc
    except Exception as exc:
        logger.exception("Apply changes failed")
        raise HTTPException(status_code=500, detail="Apply changes failed.") from exc


@app.post("/diff", response_model=RepoDiffResponse)
def diff(request: RepoDiffRequest) -> RepoDiffResponse:
    try:
        repo_id = repo_id_from_url(request.repo_url)
        repo_path = existing_repo_path(repo_id)
        repo_diff = run_git(repo_path, ["diff", "--", "."])
        return RepoDiffResponse(repo_id=repo_id, diff=repo_diff)
    except Exception as exc:
        logger.exception("Repo diff failed")
        raise HTTPException(status_code=500, detail="Repo diff failed.") from exc


@app.post("/commit", response_model=CommitResponse)
def commit(request: CommitRequest) -> CommitResponse:
    try:
        repo_id = repo_id_from_url(request.repo_url)
        message = build_commit_message(request.issue_key, request.summary, request.body)
        commit_sha = "created-by-apply-changes"

        return CommitResponse(
            repo_id=repo_id,
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
        repo_id = repo_id_from_url(request.repo_url)
        branch = request.branch
        if not branch:
            raise ValueError("Missing branch.")
        return PushResponse(repo_id=repo_id, branch=branch)
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

        repo_id = repo_id_from_url(request.repo_url)
        head_branch = request.head_branch
        if not head_branch:
            raise ValueError("Could not determine PR head branch.")

        owner, repo = github_owner_repo(request.repo_url)
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
            repo_id=repo_id,
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
