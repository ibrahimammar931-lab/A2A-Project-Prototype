import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from openai import OpenAI

from config import GROQ_API_KEY, GROQ_MODEL, check_config, configure_logging
from schemas import FileChange

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Knowledge Agent Service", version="1.0.0")


IGNORED_DIRS = {".git", "node_modules", "__pycache__", "build", "dist", "venv", ".venv", "env", "knowledge", ".pytest_cache", ".mypy_cache"}
SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".kt", ".md", ".yaml", ".yml", ".json"}


class KnowledgeAgent:
    def __init__(self) -> None:
        check_config()
        self.client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

    def _knowledge_dir(self, repository_path: str) -> Path:
        return Path(repository_path).resolve() / "knowledge"

    def _files_dir(self, repository_path: str) -> Path:
        return self._knowledge_dir(repository_path) / "files"

    def ensure_knowledge(self, repository_path: str) -> Dict[str, Any]:
        """Return loaded knowledge; build if missing."""
        knowledge_dir = self._knowledge_dir(repository_path)
        if not knowledge_dir.exists():
            logger.info("Knowledge directory missing — building knowledge for %s", repository_path)
            metadata = self.build_knowledge(repository_path)
            return metadata

        logger.info("Loading existing knowledge for %s", repository_path)
        return self.load_knowledge(repository_path)

    def build_knowledge(self, repository_path: str) -> Dict[str, Any]:
        """Scan repository and build per-file knowledge artifacts (do not store code).

        Returns metadata dict.
        """
        repo = Path(repository_path).resolve()
        if not repo.exists():
            raise ValueError(f"Repository path does not exist: {repository_path}")

        knowledge_dir = self._knowledge_dir(repository_path)
        if knowledge_dir.exists():
            logger.info("Removing existing knowledge before rebuild: %s", knowledge_dir)
            shutil.rmtree(knowledge_dir)

        files_dir = self._files_dir(repository_path)
        files_dir.mkdir(parents=True, exist_ok=True)

        summary_count = 0
        knowledge_dir = self._knowledge_dir(repository_path)
        for path in repo.rglob("**/*"):
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
            knowledge = self._summarize_file(str(rel), content)

            out_path = files_dir / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_file = out_path.with_suffix(".json")
            out_file.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
            summary_count += 1

        metadata = {
            "version": 1,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "repository": str(repo),
            "files": summary_count,
        }

        metadata_path = self._knowledge_dir(repository_path) / "metadata.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info("Built knowledge for %s (%d files)", repository_path, summary_count)
        return metadata

    def update_knowledge(self, repository_path: str, changes: List[FileChange]) -> Dict[str, Any]:
        """Update knowledge for the provided changed files only."""
        repo = Path(repository_path).resolve()
        if not repo.exists():
            raise ValueError(f"Repository path does not exist: {repository_path}")

        files_dir = self._files_dir(repository_path)
        files_dir.mkdir(parents=True, exist_ok=True)

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

            target_file = repo / rel_path
            if not target_file.exists():
                # If the file no longer exists, remove knowledge if present
                if knowledge_file.exists():
                    knowledge_file.unlink()
                    removed += 1
                continue

            try:
                content = target_file.read_text(encoding="utf-8")
            except Exception:
                logger.warning("Could not read changed file for knowledge update: %s", target_file)
                continue

            knowledge = self._summarize_file(str(rel_path), content)
            knowledge_file.parent.mkdir(parents=True, exist_ok=True)
            knowledge_file.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
            updated += 1

        # update metadata
        metadata_path = self._knowledge_dir(repository_path) / "metadata.json"
        metadata = {}
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                metadata = {}

        metadata["generated_at"] = datetime.utcnow().isoformat() + "Z"
        # update files count
        files = list((files_dir).rglob("*.json"))
        metadata["files"] = len(files)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info("Knowledge update complete: %d updated, %d removed", updated, removed)
        return {"updated": updated, "removed": removed, "metadata": metadata}

    def load_knowledge(self, repository_path: str) -> Dict[str, Any]:
        knowledge_dir = self._knowledge_dir(repository_path)
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

    def _summarize_file(self, rel_path: str, content: str) -> Dict[str, Any]:
        """Call the local LLM to summarize a single file into structured knowledge."""
        system = (
            "You are a project knowledge extractor. Read the file contents and produce a concise, structured JSON summary. "
            "Do NOT output source code or store the file contents. Only return JSON with the requested fields."
        )

        max_content_length = 15000
        prompt_content = content
        if len(content) > max_content_length:
            prompt_content = content[:max_content_length] + "\n\n...TRUNCATED DUE TO SIZE..."
            logger.warning("Truncated content for %s to avoid prompt size limits", rel_path)

        user_prompt = (
            f"Path: {rel_path}\n\nFile Content:\n" + prompt_content + "\n\n"
            "Produce JSON with these fields: path, file_purpose, summary, classes (list), functions (list), imports (list), exports (list), metadata (object). "
            "Keep values short and focused. If a field is empty, use an empty list or empty string/object."
        )

        try:
            response = self.client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty model response")

            data = json.loads(content)
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
            # Fallback simple extractor
            imports = []
            functions = []
            classes = []
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

            return {
                "path": rel_path,
                "file_purpose": "",
                "summary": (content[:200] + "...") if len(content) > 200 else content,
                "classes": classes,
                "functions": functions,
                "imports": imports,
                "exports": functions,
                "metadata": {},
            }


agent = KnowledgeAgent()


@app.post("/ensure-knowledge")
def ensure_knowledge_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        repository_path = payload["repository_path"]
        return agent.ensure_knowledge(repository_path)
    except Exception as exc:
        logger.exception("ensure_knowledge failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/build-knowledge")
def build_knowledge_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        repository_path = payload["repository_path"]
        return agent.build_knowledge(repository_path)
    except Exception as exc:
        logger.exception("build_knowledge failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/update-knowledge")
def update_knowledge_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        repository_path = payload["repository_path"]
        changes = [FileChange(**c) for c in payload.get("changes", [])]
        return agent.update_knowledge(repository_path, changes)
    except Exception as exc:
        logger.exception("update_knowledge failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/load-knowledge")
def load_knowledge_endpoint(repository_path: str) -> Dict[str, Any]:
    try:
        return agent.load_knowledge(repository_path)
    except Exception as exc:
        logger.exception("load_knowledge failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
