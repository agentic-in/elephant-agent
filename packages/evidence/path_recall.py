"""Fallback recall documents for durable Paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Mapping

from .recall_support import RecallCandidate

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PathRecallDocument:
    document_id: str
    kind: str
    text: str
    scope: str = "steps"
    when: datetime | None = None
    personal_model_id: str | None = None
    state_id: str | None = None
    episode_id: str | None = None
    loop_id: str | None = None
    step_id: str | None = None
    source_id: str | None = None
    metadata: Mapping[str, str] | None = None
    importance: float = 0.5

    def candidate(self) -> RecallCandidate:
        metadata = {
            **dict(self.metadata or {}),
            "document_id": self.document_id,
            "scope": self.scope,
            "episode_id": self.episode_id or "",
            "loop_id": self.loop_id or "",
            "step_id": self.step_id or "",
            "source_id": self.source_id or "",
        }
        return RecallCandidate(
            title=self.text[:72].strip() or self.kind,
            body=self.text,
            kind=self.kind,
            when=self.when,
            extra_metadata=metadata,
            importance=max(0.0, min(1.0, self.importance)),
        )


def documents_from_path_records(
    repository: Any,
    *,
    personal_model_id: str,
    limit: int,
) -> list[PathRecallDocument]:
    """Flatten durable Path learning summaries into conversation-search documents."""
    list_path_steps = getattr(repository, "list_path_steps", None)
    if not callable(list_path_steps):
        return []
    try:
        path_steps = tuple(list_path_steps(personal_model_id=personal_model_id, limit=limit))
    except TypeError:
        try:
            path_steps = tuple(list_path_steps())
        except Exception:
            LOGGER.debug("Failed to load Path recall documents using compatibility query.", exc_info=True)
            return []
    except Exception:
        LOGGER.debug("Failed to load Path recall documents using bounded query.", exc_info=True)
        return []

    paths_by_id = _paths_by_id(repository, personal_model_id=personal_model_id, limit=limit)
    documents: list[PathRecallDocument] = []
    for path_step in path_steps:
        path_id = str(getattr(path_step, "path_id", "") or "")
        path_title = str(getattr(paths_by_id.get(path_id), "title", "") or "").strip()
        documents.extend(_path_summary_documents(repository, path_step, path_title=path_title))
    return documents


def _paths_by_id(repository: Any, *, personal_model_id: str, limit: int) -> dict[str, Any]:
    list_paths = getattr(repository, "list_paths", None)
    if not callable(list_paths):
        return {}
    try:
        return {str(path.path_id): path for path in list_paths(personal_model_id=personal_model_id, limit=limit)}
    except TypeError:
        try:
            return {str(path.path_id): path for path in list_paths()}
        except Exception:
            return {}
    except Exception:
        return {}


def _path_summary_documents(repository: Any, path_step: Any, *, path_title: str) -> list[PathRecallDocument]:
    list_summaries = getattr(repository, "list_learning_summaries", None)
    if not callable(list_summaries):
        return []
    step_id = str(getattr(path_step, "path_step_id", "") or "")
    try:
        summaries = tuple(list_summaries(path_step_id=step_id, limit=5))
    except TypeError:
        try:
            summaries = tuple(list_summaries(path_step_id=step_id))
        except Exception:
            return []
    except Exception:
        return []
    documents: list[PathRecallDocument] = []
    for summary in summaries:
        text = " | ".join(
            part
            for part in (
                f"Path: {path_title}" if path_title else "",
                f"Flow step: {getattr(path_step, 'title', '')}",
                str(getattr(summary, "human_takeaway", "") or ""),
                str(getattr(summary, "knowledge", "") or ""),
                str(getattr(summary, "what_done", "") or ""),
                str(getattr(summary, "why_it_matters", "") or ""),
                str(getattr(summary, "how_it_was_done", "") or ""),
            )
            if str(part or "").strip()
        )
        if not text:
            continue
        summary_id = str(getattr(summary, "summary_id", "") or "")
        documents.append(
            PathRecallDocument(
                document_id=summary_id or step_id or text[:32],
                kind="path:learning_summary",
                text=text,
                when=getattr(summary, "created_at", None) or getattr(path_step, "updated_at", None),
                personal_model_id=getattr(path_step, "personal_model_id", None),
                step_id=step_id,
                source_id=summary_id,
                metadata={
                    "recall_source": "path_learning_summary",
                    "owner_scope": "state",
                    "path_id": str(getattr(summary, "path_id", "") or getattr(path_step, "path_id", "") or ""),
                    "path_step_id": step_id,
                    "summary_id": summary_id,
                    "summary_type": str(getattr(summary, "summary_type", "") or ""),
                },
                importance=1.0,
            )
        )
    return documents
