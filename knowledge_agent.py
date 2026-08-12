import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import litellm
from fastapi import FastAPI, HTTPException

from config import GROQ_API_KEY, LLM_MAX_TOKENS, GROQ_MODEL,  check_config, configure_logging
from schemas import FileChange

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Knowledge Agent Service", version="1.0.0")


IGNORED_DIRS = {".git", "node_modules", "__pycache__", "build", "dist", "venv", ".venv", "env", "knowledge", ".pytest_cache", ".mypy_cache"}
SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".kt", ".md", ".yaml", ".yml", ".json"}


def _branch_slug(branch: str) -> str:
    """Convert a git branch name into a filesystem-safe directory name.

    Replaces characters that are unsafe on Windows / Unix filesystems
    (``/``, ``\\``, ``:``, ``*``, ``?``, ``"``, ``<``, ``>``, ``|``)
    with ``-``.
    """
    return re.sub(r'[\/\\:*?"<>|]', "-", branch)


def _local_repo_id(repository_path: str) -> str:
    """Stable, path-derived cache key for local-mode knowledge.

    Mirrors repo_agent.py's local_repo_id in spirit, but this service keeps
    its own copy rather than importing across services. Resolving the path
    first means the same folder always produces the same id regardless of
    how it was referenced (relative vs absolute, trailing slash, symlink
    hops aside) across repeated runs.
    """
    resolved = Path(repository_path).resolve()
    digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:10]
    return f"local-{_branch_slug(resolved.name) or 'repo'}-{digest}"


# -- Git helpers -----------------------------------------------------------
#
# DESIGN NOTE: The Knowledge Agent performs its own read-only git
# operations (fetch, branch list, rev-parse, diff) directly against the
# checked-out repository on disk via subprocess.  This avoids adding a
# network round-trip to the Repo service for operations that are purely
# local lookups.  The Repo service is still responsible for cloning,
# branch creation, applying changes, and pushing — Knowledge only reads
# git state and checks out branches locally.
#
# In local mode, the same read-only commands (rev-parse, diff, show,
# branch --show-current) are still safe to run unmodified against a real
# local checkout — see the constraint in the task spec. Only the
# unconditional `fetch --all --prune` in ensure_knowledge is skipped for
# local mode, and it is skipped at the call site below, not in this
# helper layer, so these git helpers stay identical between modes.

def _run_git(repo_path: Path, args: list[str]) -> str:
    """Run a read-only git command in *repo_path* and return stdout."""
    command = ["git", *args]
    logger.debug("Running git command: %s", " ".join(command))
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


def _get_head_sha(repo_path: Path, branch: str) -> str | None:
    """Return the commit SHA for the tip of *branch*, or None if unresolvable.

    DESIGN CHOICE: the remote-tracking ref (``refs/remotes/origin/<branch>``)
    is checked *first*, ahead of the local ref. Changes land on GitHub via
    the Contents API (see ``_read_file_at_commit`` below) rather than local
    commits, so after a ``git fetch`` the remote-tracking ref is what
    actually reflects the branch's true current tip — a stale local ref
    left over from an earlier checkout would otherwise report an outdated
    SHA and make already-synced branches look up to date when they are not.

    For a plain (non-git) local-mode folder, or a local git checkout with
    no matching ref, both rev-parse attempts fail and this returns None —
    callers already treat that as "can't resolve HEAD" and degrade
    gracefully (skip drift refresh, record source_sha="unknown").
    """
    try:
        sha = _run_git(repo_path, ["rev-parse", f"refs/remotes/origin/{branch}"])
        return sha
    except RuntimeError:
        pass
    try:
        sha = _run_git(repo_path, ["rev-parse", f"refs/heads/{branch}"])
        return sha
    except RuntimeError:
        return None


def _list_remote_branches(repo_path: Path) -> set[str]:
    """Return the set of branch names known on origin (stripped of 'origin/').

    DESIGN CHOICE: enumerating remote branches (seen by everyone) rather
    than local branches gives a more accurate picture of what still
    "exists" — a branch that was merged via PR and had its remote ref
    deleted won't appear here, so its knowledge folder will be cleaned up
    automatically without needing any separate merge-detection logic.
    """
    try:
        raw = _run_git(repo_path, ["branch", "-r", "--no-color"])
    except RuntimeError:
        return set()

    branches: set[str] = set()
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("origin/"):
            name = line.removeprefix("origin/")
            # Skip HEAD symbolic ref
            if name and name != "HEAD":
                branches.add(name)
    return branches


def _current_branch(repo_path: Path) -> str | None:
    """Return the currently checked-out branch name, or None."""
    try:
        return _run_git(repo_path, ["branch", "--show-current"]) or None
    except RuntimeError:
        return None


def _read_file_at_commit(repo_path: Path, sha: str, path: str) -> str | None:
    """Read a file's content directly from git's object store at a specific
    commit, bypassing the working tree entirely.

    IMPORTANT: this project applies Developer changes via the GitHub
    Contents API (see the Repo service's ``apply_changes`` /
    ``github_put_file``), not local ``git commit``/``git push``. That means
    a local clone's checked-out working-tree files can go stale relative to
    the real commit history — ``git fetch`` updates remote-tracking refs,
    but nothing pulls the new file contents into the working directory.
    Reading via ``git show <sha>:<path>`` instead reads straight from the
    commit's tree object, so it is correct regardless of whether the
    working tree has been refreshed.

    Returns None if the path does not exist at that commit (e.g. it was
    deleted), distinguishing "genuinely absent" from other read failures.

    NOTE: in local mode this path is effectively unused for content lookup
    — local `apply_changes` writes to the working tree directly (no commit
    at all) and the orchestrator always calls `/update-knowledge` with
    explicit `content` already attached to each FileChange (Developer's own
    output), so `update_knowledge`'s content=None branch that calls this
    is only ever exercised for the read-only git-history drift-refresh
    path, which is fine for a real git checkout in local mode.
    """
    posix_path = path.replace("\\", "/")
    try:
        return _run_git(repo_path, ["show", f"{sha}:{posix_path}"])
    except RuntimeError as exc:
        message = str(exc).lower()
        if "does not exist" in message or "exists on disk, but not in" in message or "fatal: path" in message:
            return None
        raise


# -- Knowledge agent -------------------------------------------------------

class KnowledgeAgent:
    def __init__(self) -> None:
        check_config()
        self.model = GROQ_MODEL

    # -- Branch-scoped directory helpers -----------------------------------

    def _knowledge_dir(self, repository_path: str, branch: str, local: bool = False) -> Path:
        slug = _branch_slug(branch)
        if local:
            return LOCAL_KNOWLEDGE_ROOT.resolve() / _local_repo_id(repository_path) / slug
        return Path(repository_path).resolve() / "knowledge" / slug

    def _files_dir(self, repository_path: str, branch: str, local: bool = False) -> Path:
        return self._knowledge_dir(repository_path, branch, local=local) / "files"

    def _read_metadata(self, repository_path: str, branch: str, local: bool = False) -> dict[str, Any]:
        metadata_path = self._knowledge_dir(repository_path, branch, local=local) / "metadata.json"
        if metadata_path.exists():
            try:
                return json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _write_metadata(self, repository_path: str, branch: str, metadata: dict[str, Any], local: bool = False) -> None:
        metadata_path = self._knowledge_dir(repository_path, branch, local=local) / "metadata.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    # -- Drift refresh (shared) ---------------------------------------------

    def _refresh_if_drifted(
        self,
        repository_path: str,
        branch: str,
        model: str | None = None,
        local: bool = False,
    ) -> Tuple[Dict[str, Any], bool]:
        """Bring a branch's knowledge up to date with its current HEAD, if needed.

        Compares the branch's stored ``source_sha`` against its actual
        current HEAD (resolved via ``_get_head_sha``, which prefers the
        remote-tracking ref). If they match, nothing happens. If they
        differ, this diffs ``stored_sha..current_sha`` and patches in only
        the changed files via ``update_knowledge`` — the same targeted,
        LLM-only-where-needed approach ``sync_all_branches`` has always
        used, now factored out so ``ensure_knowledge`` and
        ``_copy_branch_knowledge`` can call it too instead of only ever
        refreshing during an explicit ``/sync-branches`` run.

        Returns ``(metadata, drifted)`` where ``drifted`` is True if the
        branch's knowledge content actually changed (rebuilt or patched),
        and False if it was already current, could not be resolved, or the
        SHA moved without any file-level changes (e.g. an empty merge).

        In local mode this only ever touches read-only git commands
        (rev-parse, diff, show), which is exactly what the local-mode
        contract allows. For a plain non-git local folder, ``_get_head_sha``
        returns None and this bails out on the "cannot resolve HEAD" branch
        below — no rebuild, no error, existing knowledge is used as-is.
        """
        repo = Path(repository_path).resolve()
        metadata = self._read_metadata(repository_path, branch, local=local)
        stored_sha = metadata.get("source_sha")
        current_sha = _get_head_sha(repo, branch)

        if current_sha is None:
            logger.warning("Cannot resolve HEAD for branch %s — skipping drift refresh", branch)
            return metadata, False

        if stored_sha == current_sha:
            return metadata, False

        logger.info(
            "Branch %s drifted from %s to %s — refreshing knowledge",
            branch,
            stored_sha or "unknown",
            current_sha,
        )

        if not stored_sha:
            # No baseline to diff against — rebuild fully.
            return self.build_knowledge(repository_path, branch, model=model, local=local), True

        try:
            changed_files_raw = _run_git(repo, ["diff", "--name-only", stored_sha, current_sha])
        except RuntimeError:
            # Old SHA isn't reachable (e.g. force-push) — rebuild from scratch.
            logger.warning(
                "Cannot diff %s..%s for branch %s — rebuilding from scratch",
                stored_sha,
                current_sha,
                branch,
            )
            return self.build_knowledge(repository_path, branch, model=model, local=local), True

        changed_paths = [p.strip() for p in changed_files_raw.splitlines() if p.strip()]

        if not changed_paths:
            # SHA moved but nothing file-level changed (e.g. an empty merge
            # commit) — just bump source_sha, no content to refresh.
            metadata["source_sha"] = current_sha
            metadata["generated_at"] = datetime.utcnow().isoformat() + "Z"
            self._write_metadata(repository_path, branch, metadata, local=local)
            return metadata, False

        # BUG FIX: this used to decide update-vs-delete by checking
        # `(repo / path).exists()` against the local working tree. That is
        # the wrong source of truth — per the design note on
        # `_read_file_at_commit`, changes land via the GitHub Contents API,
        # not local commits, so the working tree is very often checked out
        # to an entirely different branch or a stale commit. A file that
        # genuinely exists on `branch` at `current_sha` but happens to be
        # absent from whatever is currently checked out locally would get
        # misclassified as "delete" here, wiping out its knowledge entry
        # even though the file is present and unchanged content-wise —
        # producing near-empty knowledge for a branch that actually has
        # plenty of files. `update_knowledge` already resolves this
        # correctly and safely: for action="update" with content=None it
        # reads via `_read_file_at_commit` (git's object store at the real
        # commit, bypassing the working tree) and treats a genuine "not
        # present at that commit" result as a delete on its own. So every
        # changed path is passed through as "update" and update_knowledge
        # makes the real update-vs-delete call using git, not the disk.
        changes: List[FileChange] = [
            FileChange(path=path, action="update", content=None) for path in changed_paths
        ]

        result = self.update_knowledge(repository_path, branch, changes, model=model, local=local)
        return result["metadata"], True

    # -- Public API (branch-scoped) ----------------------------------------

    def ensure_knowledge(
        self,
        repository_path: str,
        branch: str,
        known_parent: str | None = None,
        model: str | None = None,
        local: bool = False,
    ) -> Dict[str, Any]:
        """Return loaded knowledge; build (or copy from a known parent) if missing.

        If the branch has no knowledge yet and ``known_parent`` is given and
        already has knowledge, the parent's knowledge is copied via a plain
        filesystem copy (no LLM calls) rather than rebuilding from scratch —
        a brand-new branch starts identical to its base, so copying is both
        cheaper and correct. Whatever the branch's own work changes later
        gets patched in by the normal ``update_knowledge`` call at the end
        of the workflow (e.g. Repo-final applying the Developer's changes).

        In git mode, this fetches remote state up front so SHA comparisons
        below reflect the real current tip on GitHub. In local mode the
        fetch is skipped entirely — local mode has no `origin` fetch
        contract at all (the workflow never mutates or syncs with a
        remote), and running it unconditionally against a real local
        checkout's `origin` would violate the "no git mutation" rule for
        local mode even though `fetch` is nominally read-only, since it can
        still write into the user's own `.git` (remote-tracking refs,
        reflogs) without their asking for it.
        """
        repo = Path(repository_path).resolve()
        if not local:
            try:
                _run_git(repo, ["fetch", "--all", "--prune"])
            except RuntimeError as exc:
                logger.warning("Fetch failed during ensure_knowledge for %s: %s", branch, exc)

        knowledge_dir = self._knowledge_dir(repository_path, branch, local=local)
        if not knowledge_dir.exists():
            if known_parent:
                parent_dir = self._knowledge_dir(repository_path, known_parent, local=local)
                if parent_dir.exists():
                    logger.info(
                        "Knowledge directory missing for branch %s — copying from known parent '%s'",
                        branch,
                        known_parent,
                    )
                    # Refresh the parent first so we copy a baseline that
                    # reflects its true current state, not a stale one that
                    # predates commits which have since landed on GitHub.
                    self._refresh_if_drifted(repository_path, known_parent, model=model, local=local)
                    self._copy_branch_knowledge(repository_path, known_parent, branch, model=model, local=local)
                    return self.load_knowledge(repository_path, branch, local=local)
                logger.info(
                    "Known parent '%s' has no knowledge either — falling back to full build for %s",
                    known_parent,
                    branch,
                )
            else:
                logger.info(
                    "Knowledge directory missing for branch %s and no known parent given — building from scratch",
                    branch,
                )
            self.build_knowledge(repository_path, branch, model=model, local=local)
            # NOTE: build_knowledge/_copy_branch_knowledge return the raw
            # metadata dict (where "files" is an integer count). Callers of
            # ensure_knowledge (e.g. the Planner) expect the same shape as
            # load_knowledge returns (where "files" is a dict of per-file
            # summaries keyed by path). Returning the raw metadata dict here
            # caused an intermittent AttributeError downstream whenever
            # knowledge had to be built or copied fresh this run, since
            # `.get("files").keys()` only works on the dict shape — it
            # worked "sometimes" because a branch with pre-existing
            # knowledge took the load_knowledge path below instead and never
            # hit this bug. Always route through load_knowledge here so
            # ensure_knowledge has exactly one return shape, always.
            return self.load_knowledge(repository_path, branch, local=local)

        logger.info("Loading existing knowledge for %s (branch %s)", repository_path, branch)
        # The branch may have moved since knowledge was last built or
        # updated — refresh any drift before handing knowledge back. This
        # only uses read-only git commands, so it's safe to run in local
        # mode against a real checkout; for a plain non-git folder or one
        # with no resolvable HEAD it's a no-op (see _refresh_if_drifted).
        self._refresh_if_drifted(repository_path, branch, model=model, local=local)
        return self.load_knowledge(repository_path, branch, local=local)

    def build_knowledge(self, repository_path: str, branch: str, model: str | None = None, local: bool = False) -> Dict[str, Any]:
        """Scan repository and build per-file knowledge artifacts (do not store code).

        Records the current HEAD commit SHA as ``source_sha`` in metadata
        so subsequent sync runs can detect drift. In local mode against a
        plain (non-git) folder, ``_get_head_sha`` resolves to None and
        ``source_sha`` is recorded as ``"unknown"`` — this is expected and
        handled gracefully everywhere source_sha is read.
        """
        repo = Path(repository_path).resolve()
        if not repo.exists():
            raise ValueError(f"Repository path does not exist: {repository_path}")

        knowledge_dir = self._knowledge_dir(repository_path, branch, local=local)
        if knowledge_dir.exists():
            logger.info("Removing existing knowledge before rebuild: %s", knowledge_dir)
            shutil.rmtree(knowledge_dir)

        files_dir = self._files_dir(repository_path, branch, local=local)
        files_dir.mkdir(parents=True, exist_ok=True)

        summary_count = 0
        knowledge_dir = self._knowledge_dir(repository_path, branch, local=local)
        for path in repo.rglob("**/*"):
            # In local mode knowledge_dir lives outside repo entirely (under
            # LOCAL_KNOWLEDGE_ROOT), so this check simply never matches —
            # left unconditional since it's a correct no-op either way.
            if path == knowledge_dir or knowledge_dir in path.parents:
                logger.debug("Skipping generated knowledge path: %s", path)
                continue

            if path.is_dir():
                if path.name in IGNORED_DIRS:
                    logger.debug("Skipping ignored directory: %s", path)
                    continue
                continue

            if any(part in IGNORED_DIRS for part in path.parts):
                logger.debug("Skipping path inside ignored dir: %s", path)
                continue

            if path.suffix.lower() not in SOURCE_EXTENSIONS:
                continue

            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                logger.debug("Skipping non-text or unreadable file: %s", path)
                continue

            rel = path.relative_to(repo)
            knowledge = self._summarize_file(str(rel), content, model=model)

            out_path = files_dir / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_file = out_path.with_suffix(".json")
            out_file.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
            summary_count += 1

        # Resolve the current HEAD for this branch to record as source_sha
        source_sha = _get_head_sha(repo, branch) or "unknown"

        metadata = {
            "version": 1,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "repository": str(repo),
            "branch": branch,
            "files": summary_count,
            "source_sha": source_sha,
            "local": local,
        }

        metadata_path = self._knowledge_dir(repository_path, branch, local=local) / "metadata.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info("Built knowledge for %s branch %s (%d files, SHA %s)", repository_path, branch, summary_count, source_sha)
        return metadata

    def _copy_branch_knowledge(
        self,
        repository_path: str,
        source_branch: str,
        new_branch: str,
        model: str | None = None,
        local: bool = False,
    ) -> Dict[str, Any]:
        """Copy an existing branch's knowledge into a new branch's knowledge
        directory via a plain filesystem copy — no LLM calls. Used when a new
        branch is created and its base branch already has knowledge.

        After copying, updates the copied metadata's `branch` field to
        `new_branch` and its `source_sha` to `new_branch`'s own current HEAD
        (at creation time this should equal the source's HEAD, since the new
        branch was just forked from it — but resolving it explicitly for the
        new branch, rather than reusing the source's SHA, keeps this correct
        even if called slightly after creation, e.g. if a commit or two has
        already landed on the new branch before this runs).

        IMPORTANT: relabeling metadata's ``source_sha`` to ``new_branch``'s
        current HEAD is not, by itself, enough to make that true — the files
        that were actually copied only reflect content as of the *source*
        branch's own ``source_sha`` at copy time. If ``new_branch`` already
        has commits beyond that baseline (the case described above), simply
        overwriting the label would mask the drift: the metadata would claim
        to be current as of ``new_branch``'s HEAD while the file contents
        still describe the older, copied baseline. So after relabeling, this
        diffs the copied baseline against ``new_branch``'s actual HEAD and,
        if they differ, patches in the difference via ``update_knowledge``
        so the copy is genuinely accurate rather than just labeled as such.

        Not called at all in local mode's own new-branch path today (local
        mode never creates a branch), but kept local-aware since
        ensure_knowledge's known_parent copy path can still reach it — e.g.
        a local checkout whose current branch has no knowledge yet but a
        base branch's local-mode knowledge already exists in the cache.
        """
        source_dir = self._knowledge_dir(repository_path, source_branch, local=local)
        if not source_dir.exists():
            raise ValueError(
                f"Cannot copy knowledge: source branch '{source_branch}' has no existing knowledge"
            )

        dest_dir = self._knowledge_dir(repository_path, new_branch, local=local)
        if dest_dir.exists():
            logger.info("Removing existing knowledge before copy: %s", dest_dir)
            shutil.rmtree(dest_dir)

        shutil.copytree(source_dir, dest_dir)

        repo = Path(repository_path).resolve()
        new_branch_sha = _get_head_sha(repo, new_branch)

        metadata = self._read_metadata(repository_path, new_branch, local=local)
        # The SHA the copied files actually reflect, before we relabel it.
        copied_baseline_sha = metadata.get("source_sha")
        metadata["branch"] = new_branch
        metadata["generated_at"] = datetime.utcnow().isoformat() + "Z"
        if new_branch_sha:
            metadata["source_sha"] = new_branch_sha
        self._write_metadata(repository_path, new_branch, metadata, local=local)

        if (
            new_branch_sha
            and copied_baseline_sha
            and copied_baseline_sha != new_branch_sha
        ):
            logger.info(
                "Copied baseline for %s (%s) differs from its actual HEAD (%s) — refreshing to catch up",
                new_branch,
                copied_baseline_sha,
                new_branch_sha,
            )
            try:
                changed_files_raw = _run_git(repo, ["diff", "--name-only", copied_baseline_sha, new_branch_sha])
                changed_paths = [p.strip() for p in changed_files_raw.splitlines() if p.strip()]
                if changed_paths:
                    # Same fix as _refresh_if_drifted: don't classify
                    # update-vs-delete from `(repo / path).exists()` — the
                    # working tree may not be checked out to `new_branch` at
                    # all, so that check tells us nothing reliable about
                    # what actually exists on this branch. Pass every path
                    # through as "update" with content=None and let
                    # update_knowledge resolve real existence via
                    # `_read_file_at_commit` against `new_branch_sha`
                    # itself.
                    changes: List[FileChange] = [
                        FileChange(path=path, action="update", content=None) for path in changed_paths
                    ]
                    update_result = self.update_knowledge(repository_path, new_branch, changes, model=model, local=local)
                    metadata = update_result["metadata"]
            except RuntimeError as exc:
                logger.warning(
                    "Could not diff %s..%s to refresh copied knowledge for %s (%s) — leaving as copied",
                    copied_baseline_sha,
                    new_branch_sha,
                    new_branch,
                    exc,
                )

        logger.info(
            "Copied knowledge for branch '%s' from '%s' (%d files, SHA %s)",
            new_branch,
            source_branch,
            metadata.get("files", 0),
            metadata.get("source_sha", "unknown"),
        )
        return metadata

    def update_knowledge(
        self,
        repository_path: str,
        branch: str,
        changes: List[FileChange],
        model: str | None = None,
        local: bool = False,
    ) -> Dict[str, Any]:
        """Update knowledge for the provided changed files only.

        Updates ``source_sha`` in metadata to the branch's current HEAD.

        NOTE ON CONTENT SOURCE: when a change does not carry explicit
        ``content`` (``content is None``), this reads the file from git's
        object store at the branch's current commit (via
        ``_read_file_at_commit`` / ``git show <sha>:<path>``) rather than
        from the working-tree file on disk. This matters because changes
        are applied via the GitHub Contents API (one commit per file,
        directly on GitHub) in git mode, not local ``git commit``/``git
        push`` — so the local working tree is not guaranteed to reflect the
        latest commits even after a ``git fetch``. Reading from the object
        store at the known commit SHA is correct regardless of working-tree
        state.

        LOCAL MODE: local `apply_changes` writes plain files directly with
        no commit at all, so there is no new commit for this content=None
        path to read from — but it never needs to: the orchestrator's
        `_run_repo_final` always calls `/update-knowledge` with `content`
        already attached to each FileChange (straight from the Developer's
        own output), so the content=None / `_read_file_at_commit` branch is
        only ever exercised by the read-only drift-refresh callers
        (`_refresh_if_drifted`, `_copy_branch_knowledge`) against a real git
        checkout, where reading historical commits is legitimate.
        """
        repo = Path(repository_path).resolve()
        if not repo.exists():
            raise ValueError(f"Repository path does not exist: {repository_path}")

        files_dir = self._files_dir(repository_path, branch, local=local)
        files_dir.mkdir(parents=True, exist_ok=True)

        # Resolve once up front: every content=None read in this call uses
        # this same commit, so all files summarized in one pass are
        # consistent with a single, real point in the branch's history.
        current_sha = _get_head_sha(repo, branch)

        updated = 0
        removed = 0
        for change in changes:
            rel_path = Path(change.path)
            knowledge_file = files_dir / rel_path
            knowledge_file = knowledge_file.with_suffix(".json")

            action = change.action.lower().strip()
            if action in {"delete", "removed"}:
                if knowledge_file.exists():
                    knowledge_file.unlink()
                    removed += 1
                    logger.info("Removed knowledge for deleted file: %s", change.path)
                continue

            if change.content is not None:
                content = change.content
            else:
                if not current_sha:
                    logger.warning(
                        "Could not resolve current commit for branch %s — skipping %s",
                        branch,
                        change.path,
                    )
                    continue

                try:
                    content = _read_file_at_commit(repo, current_sha, change.path)
                except RuntimeError as exc:
                    logger.warning(
                        "Could not read %s at commit %s for knowledge update: %s",
                        change.path,
                        current_sha,
                        exc,
                    )
                    continue

                if content is None:
                    # File does not exist at this commit — treat like a delete.
                    if knowledge_file.exists():
                        knowledge_file.unlink()
                        removed += 1
                        logger.info(
                            "Removed knowledge for %s (not present at commit %s)",
                            change.path,
                            current_sha,
                        )
                    continue

            knowledge = self._summarize_file(str(rel_path), content, model=model)
            knowledge_file.parent.mkdir(parents=True, exist_ok=True)
            knowledge_file.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
            updated += 1

        # Update metadata including source_sha
        metadata = self._read_metadata(repository_path, branch, local=local)
        metadata["generated_at"] = datetime.utcnow().isoformat() + "Z"
        metadata["branch"] = branch

        # Record current HEAD as the new source_sha (reuse the SHA resolved
        # at the top of this call, so metadata reflects exactly the commit
        # every content=None read in this call actually used). In local
        # mode against a plain non-git folder, current_sha is None and this
        # falls back to whatever was already stored (or "unknown").
        source_sha = current_sha or metadata.get("source_sha", "unknown")
        metadata["source_sha"] = source_sha

        # Update files count
        files = list(files_dir.rglob("*.json"))
        metadata["files"] = len(files)

        self._write_metadata(repository_path, branch, metadata, local=local)

        logger.info("Knowledge update complete for branch %s: %d updated, %d removed (SHA %s)", branch, updated, removed, source_sha)
        return {"updated": updated, "removed": removed, "metadata": metadata}

    def load_knowledge(self, repository_path: str, branch: str, local: bool = False) -> Dict[str, Any]:
        knowledge_dir = self._knowledge_dir(repository_path, branch, local=local)
        if not knowledge_dir.exists():
            raise ValueError("Knowledge not found; build it first.")

        files_dir = knowledge_dir / "files"
        result: Dict[str, Any] = {"metadata": {}, "files": {}}
        metadata_path = knowledge_dir / "metadata.json"
        if metadata_path.exists():
            try:
                result["metadata"] = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                result["metadata"] = {}

        if files_dir.exists():
            for p in files_dir.rglob("*.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                key = data.get("path") or str(p.relative_to(files_dir))
                result["files"][key] = data

        return result

    # -- Automatic branch sync ---------------------------------------------
    #
    # sync_all_branches / _delete_branch_knowledge intentionally take no
    # `local` parameter and are never called in local mode — the whole
    # point of /sync-branches is deleting knowledge for branches missing
    # from `git branch -r`, and local mode has no `origin`, so that list is
    # always empty and it would delete nearly all local knowledge on every
    # run. The orchestrator gates this call on `if not self.local_path`, so
    # these two methods simply never run for a local-mode workflow.

    def _delete_branch_knowledge(self, repository_path: str, branch: str) -> None:
        """Delete a branch's entire knowledge directory.

        Used during sync when a branch no longer exists on the remote.
        """
        knowledge_dir = self._knowledge_dir(repository_path, branch)
        if knowledge_dir.exists():
            shutil.rmtree(knowledge_dir)
            logger.info("Deleted knowledge directory for branch %s: %s", branch, knowledge_dir)

    def sync_all_branches(self, repository_path: str, model: str | None = None) -> Dict[str, Any]:
        """Bring every branch's knowledge in sync with the current git state.

        For brand-new branches that have no knowledge folder yet, this
        method first tries to copy from the repository's configured
        default base branch (via ``_copy_branch_knowledge``) if that
        branch already has knowledge — no LLM calls. Only when there is
        no base to copy from does it fall back to a full ``build_knowledge``
        rebuild. Note this housekeeping path has no per-branch context
        about what a given branch's actual intended parent was (unlike the
        orchestrator-driven ``ensure_knowledge(..., known_parent=...)``
        path used during normal workflow runs), so it can only guess the
        configured default base branch.

        Branches that already have knowledge are brought up to date via the
        same ``_refresh_if_drifted`` helper ``ensure_knowledge`` uses, so
        both paths detect and patch drift identically instead of keeping
        separate copies of the diff-and-patch logic.

        Returns a summary like::

            {
              "created": ["agent/KAN-20-new-thing"],
              "updated": ["main"],
              "deleted": ["agent/KAN-17-add-roles"],
              "unchanged": ["agent/KAN-18-other"]
            }
        """
        repo = Path(repository_path).resolve()
        if not repo.exists():
            raise ValueError(f"Repository path does not exist: {repository_path}")

        # Fetch all remote state so we see the latest branch list and SHAs
        logger.info("Fetching all remotes for branch sync")
        try:
            _run_git(repo, ["fetch", "--all", "--prune"])
        except RuntimeError as exc:
            logger.warning("Fetch failed during sync: %s", exc)

        # Enumerate real branches
        remote_branches = _list_remote_branches(repo)
        logger.info("Remote branches found: %s", sorted(remote_branches))

        # Determine the currently checked-out branch so we never delete
        # knowledge for it, even if it temporarily doesn't appear in the
        # remote list (e.g. not yet pushed or mid-workflow).
        current = _current_branch(repo)

        # Enumerate knowledge folders that exist on disk
        knowledge_root = repo / "knowledge"
        existing_knowledge_branches: set[str] = set()
        if knowledge_root.exists():
            for entry in knowledge_root.iterdir():
                if entry.is_dir():
                    # Map back from slug to branch name: this is lossy (two
                    # different branch names could slug to the same dir), but
                    # since the original branch name is preserved in
                    # metadata.json we can recover it.
                    metadata_path = entry / "metadata.json"
                    if metadata_path.exists():
                        try:
                            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                            branch_name = meta.get("branch")
                            if branch_name:
                                existing_knowledge_branches.add(branch_name)
                                continue
                        except Exception:
                            pass
                    # Fallback: use the directory name as the branch name
                    # (this handles knowledge folders created before branch
                    # was recorded in metadata).
                    existing_knowledge_branches.add(entry.name)

        created: list[str] = []
        updated: list[str] = []
        deleted: list[str] = []
        unchanged: list[str] = []

        default_base = os.getenv("DEFAULT_BASE_BRANCH", "main")

        # a & b. For every existing branch, create or update knowledge
        for branch in sorted(remote_branches):
            knowledge_dir = self._knowledge_dir(repository_path, branch)

            if not knowledge_dir.exists():
                # New branch — try copying from the default base branch first
                default_base_dir = self._knowledge_dir(repository_path, default_base)
                if branch != default_base and default_base_dir.exists():
                    logger.info(
                        "Sync: copying knowledge for new branch %s from default base '%s'",
                        branch,
                        default_base,
                    )
                    # Refresh the base first so new branches are copied from
                    # an up-to-date baseline, then let _copy_branch_knowledge's
                    # own catch-up refresh handle any commits already on
                    # `branch` beyond that baseline.
                    self._refresh_if_drifted(repository_path, default_base, model=model)
                    self._copy_branch_knowledge(repository_path, default_base, branch, model=model)
                else:
                    logger.info(
                        "Sync: building knowledge for new branch %s (no base to copy from)",
                        branch,
                    )
                    self.build_knowledge(repository_path, branch, model=model)
                created.append(branch)
                continue

            # Branch exists and has knowledge — refresh it if it has drifted,
            # using the same shared logic ensure_knowledge relies on.
            _metadata, drifted = self._refresh_if_drifted(repository_path, branch, model=model)
            if drifted:
                updated.append(branch)
            else:
                unchanged.append(branch)

        # c. Delete knowledge for branches that no longer exist
        for branch in sorted(existing_knowledge_branches):
            if branch in remote_branches:
                continue  # still exists, handled above

            # Never delete the currently checked-out branch's knowledge,
            # even if it doesn't appear in the remote list yet (e.g.
            # mid-workflow, not yet pushed, or briefly stale after a
            # checkout).
            if current and branch == current:
                logger.info(
                    "Sync: skipping deletion of knowledge for currently checked-out branch %s",
                    branch,
                )
                unchanged.append(branch)
                continue

            logger.info("Sync: branch %s no longer exists — deleting knowledge", branch)
            self._delete_branch_knowledge(repository_path, branch)
            deleted.append(branch)

        summary = {
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "unchanged": unchanged,
        }
        logger.info("Branch sync complete: %s", summary)
        return summary

    # -- Summarization (LLM) ----------------------------------------------

    def _summarize_file(self, rel_path: str, content: str, model: str | None = None) -> Dict[str, Any]:
        """Call the LLM via LiteLLM to summarize a single file into structured knowledge."""
        system = (
            "You are a project knowledge extractor. Read the file contents and produce a concise, "
            "structured JSON summary. Do NOT output source code or store the file contents. "
            "Only return JSON with the requested fields.\n\n"
            "The `summary` field must be a Markdown-formatted string (not plain text), following this shape:\n"
            "## <short file title>\n"
            "<2-3 sentence description of what this file does and why it exists>\n\n"
            "**Key functions/classes:** <comma-separated list of the most important ones, in backticks>\n\n"
            "**Depends on:** <comma-separated list of the most important imports/dependencies, in backticks>\n\n"
            "Keep the whole `summary` value under ~120 words. Do not include a top-level '#' heading, "
            "only the '##' shown above. Do not wrap the markdown in a code fence."
        )

        max_content_length = 15000
        prompt_content = content
        if len(content) > max_content_length:
            prompt_content = content[:max_content_length] + "\n\n...TRUNCATED DUE TO SIZE..."
            logger.warning("Truncated content for %s to avoid prompt size limits", rel_path)

        user_prompt = (
            f"Path: {rel_path}\n\nFile Content:\n" + prompt_content + "\n\n"
            "Produce JSON with these fields:\n"
            "- path (string)\n"
            "- file_purpose (string, ONE short plain-text sentence, no markdown)\n"
            "- summary (string, Markdown-formatted as specified in the system prompt)\n"
            "- classes (list of strings)\n"
            "- functions (list of strings)\n"
            "- imports (list of strings)\n"
            "- exports (list of strings)\n"
            "- metadata (object)\n\n"
            "If a field is empty, use an empty list or empty string/object. "
            "Only `summary` should contain Markdown — all other fields stay plain."
        )

        try:
            selected_model = model or self.model  # override from orchestrator, or fallback default
            response = litellm.completion(
                model=selected_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
                temperature=0.0,
                max_tokens=LLM_MAX_TOKENS,
                response_format={"type": "json_object"},
            )

            response_content = response.choices[0].message.content
            if not response_content:
                raise ValueError("Empty model response")

            data = json.loads(response_content)
            # Ensure required keys and types
            result = {
                "path": rel_path,
                "file_purpose": data.get("file_purpose", ""),
                "summary": data.get("summary", ""),
                "classes": data.get("classes", []),
                "functions": data.get("functions", []),
                "imports": data.get("imports", []),
                "exports": data.get("exports", []),
                "metadata": data.get("metadata", {}),
            }
            return result
        except Exception as exc:
            logger.warning("LLM summarization failed for %s: %s", rel_path, exc)
            # Fallback simple extractor — works on the file content
            # (method param `content`), not the LLM response.
            imports: list[str] = []
            functions: list[str] = []
            classes: list[str] = []
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("import ") or line.startswith("from "):
                    parts = line.split()
                    if len(parts) >= 2:
                        imports.append(parts[1])
                if line.startswith("def "):
                    functions.append(line.split("(")[0].replace("def ", ""))
                if line.startswith("class "):
                    classes.append(line.split("(")[0].replace("class ", "").strip(":"))

            fallback_summary = (content[:200] + "...") if len(content) > 200 else content
            return {
                "path": rel_path,
                "file_purpose": "",
                "summary": fallback_summary,
                "classes": classes,
                "functions": functions,
                "imports": imports,
                "exports": functions,
                "metadata": {},
            }


agent = KnowledgeAgent()


# -- FastAPI Endpoints ----------------------------------------------------


@app.post("/ensure-knowledge")
def ensure_knowledge_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        repository_path = payload["repository_path"]
        branch = payload["branch"]
        known_parent = payload.get("known_parent")
        model = payload.get("model")
        local = bool(payload.get("local", False))
        return agent.ensure_knowledge(repository_path, branch, known_parent, model=model, local=local)
    except Exception as exc:
        logger.exception("ensure_knowledge failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/build-knowledge")
def build_knowledge_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        repository_path = payload["repository_path"]
        branch = payload["branch"]
        model = payload.get("model")
        local = bool(payload.get("local", False))
        return agent.build_knowledge(repository_path, branch, model=model, local=local)
    except Exception as exc:
        logger.exception("build_knowledge failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/update-knowledge")
def update_knowledge_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        repository_path = payload["repository_path"]
        branch = payload["branch"]
        model = payload.get("model")
        local = bool(payload.get("local", False))
        changes = [FileChange(**c) for c in payload.get("changes", [])]
        return agent.update_knowledge(repository_path, branch, changes, model=model, local=local)
    except Exception as exc:
        logger.exception("update_knowledge failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/load-knowledge")
def load_knowledge_endpoint(repository_path: str, branch: str, local: bool = False) -> Dict[str, Any]:
    try:
        return agent.load_knowledge(repository_path, branch, local=local)
    except Exception as exc:
        logger.exception("load_knowledge failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/sync-branches")
def sync_branches_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Sync knowledge for every git branch against the current repo state.

    Expects ``{"repository_path": "..."}``.

    NOTE: this endpoint has no local-mode handling and must never be called
    when local mode is active — see the module-level note above
    sync_all_branches. The orchestrator is responsible for gating the call,
    not this endpoint.

    Creates knowledge for new branches (copying from the default base
    branch when it already has knowledge, otherwise building from
    scratch), updates knowledge for branches with new commits (using
    ``git diff`` between stored ``source_sha`` and current HEAD), and
    deletes knowledge for branches that no longer exist on the remote.

    All sync housekeeping is LLM-free except for genuinely new or changed
    files, which trigger summarization inside ``build_knowledge`` /
    ``update_knowledge``.
    """
    try:
        repository_path = payload["repository_path"]
        model = payload.get("model")
        return agent.sync_all_branches(repository_path, model=model)
    except Exception as exc:
        logger.exception("sync_branches failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc