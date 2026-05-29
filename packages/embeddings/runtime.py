"""Shared embedding provider contracts and canonical local-service helpers."""

from __future__ import annotations

import importlib.util
import logging
import math
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

ELEPHANT_EMBED_PROVIDER_ID = "elephant-local-embed"
ELEPHANT_EMBED_MODEL_ID = "llm-semantic-router/elephant-embeddings-v1-text-small"
ELEPHANT_EMBED_SOURCE_URL = "https://huggingface.co/llm-semantic-router/elephant-embeddings-v1-text-small"
ELEPHANT_EMBED_MODEL_ROOT = str(Path.home() / ".elephant" / "models" / "elephant-embeddings-v1-text-small")
ELEPHANT_EMBED_MODELSCOPE_ID = "agentic-intelligence-lab/elephant-embeddings-v1-text-small"
ELEPHANT_EMBED_MODELSCOPE_URL = "https://modelscope.cn/models/agentic-intelligence-lab/elephant-embeddings-v1-text-small"
ELEPHANT_EMBED_ONLINE_DIMENSIONS = (64, 256, 768)
_ALLOWED_EMBEDDING_STATUSES = frozenset({"pending", "downloading", "ready", "skipped", "failed"})
_ALLOWED_PRELOAD_STATUSES = frozenset({"idle", "steadying", "ready", "failed", "skipped"})
_DEFAULT_PRELOAD_TARGETS = ("activities", "evidence")
_DEFAULT_EMBED_BATCH_SIZE = 8
_DEFAULT_BACKFILL_FAILURE_COOLDOWN = timedelta(minutes=10)
_ALLOWED_RUNTIME_STATES = frozenset({"cold", "steadying", "loaded"})
_HEALTHY_ROOT_MARKERS = (
    "modules.json",
    "config_sentence_transformers.json",
    "sentence_bert_config.json",
)
_LOCAL_EMBEDDING_LOG_FILTER_INSTALLED = False
_LOCAL_EMBEDDING_WARNING_MODEL_ROOTS: set[str] = set()
LOGGER = logging.getLogger(__name__)


def _is_incorrect_regex_warning_for_local_embedding_root(message: str) -> bool:
    if not message.startswith("The tokenizer you are loading from "):
        return False
    if " with an incorrect regex pattern" not in message:
        return False
    return any(model_root in message for model_root in _LOCAL_EMBEDDING_WARNING_MODEL_ROOTS)


def _suppress_local_embedding_load_warnings(model_root: str | None = None) -> None:
    global _LOCAL_EMBEDDING_LOG_FILTER_INSTALLED
    _LOCAL_EMBEDDING_WARNING_MODEL_ROOTS.add(str(embedding_model_root_path(model_root)))
    if not _LOCAL_EMBEDDING_LOG_FILTER_INSTALLED:
        class _LocalEmbeddingLoadFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                message = record.getMessage()
                if message.startswith("You try to use a model that was created with version "):
                    return False
                return not _is_incorrect_regex_warning_for_local_embedding_root(message)

        for logger_name in (
            "sentence_transformers.SentenceTransformer",
            "transformers",
            "transformers.tokenization_utils_tokenizers",
        ):
            logging.getLogger(logger_name).addFilter(_LocalEmbeddingLoadFilter())
        _LOCAL_EMBEDDING_LOG_FILTER_INSTALLED = True


def _identity_torch_compile(fn: Any = None, *args: Any, **kwargs: Any) -> Any:
    del args, kwargs
    if fn is None:
        def _decorator(candidate: Any) -> Any:
            return candidate

        return _decorator
    return fn


def _patch_unsupported_torch_compile() -> None:
    """ModernBERT decorates blocks with torch.compile, which old torch cannot use on Python 3.12."""

    if sys.version_info < (3, 12):
        return
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return
    compile_fn = getattr(torch, "compile", None)
    if not callable(compile_fn) or getattr(compile_fn, "_elephant_identity_compile", False):
        return
    try:
        compile_fn(lambda value: value)
    except RuntimeError as error:
        if "Dynamo is not supported" not in str(error):
            return
        patched = _identity_torch_compile
        setattr(patched, "_elephant_identity_compile", True)
        setattr(torch, "compile", patched)
    except Exception:
        return


def _python_values(value: Any) -> Any:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def _encoded_embedding_rows(encoded: Any) -> list[Any]:
    rows = _python_values(encoded)
    if rows is None:
        return []
    if isinstance(rows, tuple):
        rows = list(rows)
    if not isinstance(rows, list):
        return [rows]
    if not rows:
        return []
    first = _python_values(rows[0])
    if isinstance(first, (list, tuple)):
        return [_python_values(row) for row in rows]
    return [rows]


def embedding_model_root_path(model_root: str | None = None) -> Path:
    configured = str(model_root or ELEPHANT_EMBED_MODEL_ROOT).strip() or ELEPHANT_EMBED_MODEL_ROOT
    return Path(configured).expanduser()


def embedding_root_is_healthy(model_root: str | None = None) -> bool:
    root = embedding_model_root_path(model_root)
    if not root.is_dir():
        return False
    return any((root / marker).is_file() for marker in _HEALTHY_ROOT_MARKERS)


def sentence_transformers_dependencies_ready() -> bool:
    return all(
        importlib.util.find_spec(module_name) is not None
        for module_name in ("sentence_transformers", "huggingface_hub")
    )


def resolve_embedding_dimensions(latency_mode: str = "balanced", *, dimensions: int | None = None) -> int:
    if dimensions is not None:
        if dimensions not in ELEPHANT_EMBED_ONLINE_DIMENSIONS:
            raise ValueError(
                f"embedding dimensions must be one of {ELEPHANT_EMBED_ONLINE_DIMENSIONS}: {dimensions}"
            )
        return dimensions
    normalized = latency_mode.strip().lower()
    if normalized in {"fast", "low-latency", "64d"}:
        return 64
    if normalized in {"deep", "offline", "768d"}:
        return 768
    return 256


def embedding_mode_for_dimensions(dimensions: int) -> str:
    resolved = resolve_embedding_dimensions(dimensions=dimensions)
    return f"{ELEPHANT_EMBED_MODEL_ID}:{resolved}d"


def embedding_mode_for_latency(latency_mode: str = "balanced") -> str:
    return embedding_mode_for_dimensions(resolve_embedding_dimensions(latency_mode))


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=False))


def _tokenize(text: str) -> tuple[str, ...]:
    return tuple(token for token in re.findall(r"[A-Za-z0-9_]+", text.lower()) if token)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_target(value: str) -> str:
    normalized = str(value).strip().lower()
    return normalized or "general"


def _normalize_embedding_values(values: tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(sum(component * component for component in values))
    if norm == 0.0:
        return tuple(0.0 for _ in values)
    return tuple(component / norm for component in values)


def embedding_runtime_state(health: EmbeddingHealth | None) -> str:
    if health is None:
        return "cold"
    metadata = getattr(health, "metadata", {})
    if isinstance(metadata, Mapping):
        candidate = str(metadata.get("runtime_state", "")).strip().lower()
        if candidate in _ALLOWED_RUNTIME_STATES:
            return candidate
    return "loaded" if str(getattr(health, "status", "")).strip().lower() == "ready" else "cold"


def embedding_runtime_is_loaded(health: EmbeddingHealth | None) -> bool:
    return embedding_runtime_state(health) == "loaded"


def _truncate_matryoshka_vector(values: tuple[float, ...], *, dimensions: int) -> tuple[float, ...]:
    if len(values) < dimensions:
        raise ValueError(f"embedding source vector must have at least {dimensions} dimensions")
    return _normalize_embedding_values(tuple(values[:dimensions]))


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    request_id: str
    texts: tuple[str, ...]
    task: str = "retrieve"
    latency_mode: str = "balanced"
    dimensions: int | None = None
    provider_id: str = ELEPHANT_EMBED_PROVIDER_ID
    model_id: str = ELEPHANT_EMBED_MODEL_ID
    metadata: Mapping[str, str] = field(default_factory=dict)

    def resolved_dimensions(self) -> int:
        return resolve_embedding_dimensions(self.latency_mode, dimensions=self.dimensions)


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    text_index: int
    provider_id: str
    model_id: str
    dimensions: int
    values: tuple[float, ...]
    source_text: str = ""

    def __post_init__(self) -> None:
        if self.dimensions not in ELEPHANT_EMBED_ONLINE_DIMENSIONS:
            raise ValueError(
                f"embedding vector dimensions must be one of {ELEPHANT_EMBED_ONLINE_DIMENSIONS}: {self.dimensions}"
            )
        if len(self.values) != self.dimensions:
            raise ValueError("embedding vector length must match dimensions")


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    request_id: str
    provider_id: str
    model_id: str
    dimensions: int
    vectors: tuple[EmbeddingVector, ...]
    task: str = "retrieve"
    latency_mode: str = "balanced"
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmbeddingHealth:
    provider_id: str
    model_id: str
    status: str
    summary: str
    supported_dimensions: tuple[int, ...] = ELEPHANT_EMBED_ONLINE_DIMENSIONS
    checked_at: datetime = field(default_factory=_utc_now)
    source_url: str = ELEPHANT_EMBED_SOURCE_URL
    model_root: str = ELEPHANT_EMBED_MODEL_ROOT
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED_EMBEDDING_STATUSES:
            raise ValueError(
                f"embedding health status must be one of {sorted(_ALLOWED_EMBEDDING_STATUSES)}: {self.status}"
            )


@dataclass(frozen=True, slots=True)
class EmbeddingPreloadEntry:
    cache_key: str
    text: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmbeddingPreloadState:
    provider_id: str
    model_id: str
    status: str
    summary: str
    ready_dimensions: tuple[int, ...] = ()
    pending_targets: tuple[str, ...] = ()
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED_PRELOAD_STATUSES:
            raise ValueError(
                f"embedding preload status must be one of {sorted(_ALLOWED_PRELOAD_STATUSES)}: {self.status}"
            )


@runtime_checkable
class EmbeddingProvider(Protocol):
    provider_id: str
    model_id: str
    supported_dimensions: tuple[int, ...]

    def embed(self, request: EmbeddingRequest) -> EmbeddingBatch: ...

    def health(self) -> EmbeddingHealth: ...

    def preload_state(self) -> EmbeddingPreloadState: ...

    def preload(
        self, *, target: str, entries: tuple[EmbeddingPreloadEntry, ...], latency_mode: str = "balanced"
    ) -> EmbeddingPreloadState: ...

    def queue_backfill(
        self, *, target: str, entries: tuple[EmbeddingPreloadEntry, ...], latency_mode: str = "balanced"
    ) -> EmbeddingPreloadState: ...

    def cached_vector(self, *, target: str, cache_key: str, dimensions: int) -> EmbeddingVector | None: ...

    def pending_vector(self, *, target: str, cache_key: str, dimensions: int) -> bool: ...

    def steady_async(self) -> bool: ...


@runtime_checkable
class EmbeddingModelRegistry(Protocol):
    def register(self, provider: EmbeddingProvider) -> None: ...

    def get(self, provider_id: str) -> EmbeddingProvider | None: ...

    def default(self) -> EmbeddingProvider: ...

    def list(self) -> tuple[EmbeddingProvider, ...]: ...


@runtime_checkable
class EmbeddingService(Protocol):
    def embed(self, request: EmbeddingRequest) -> EmbeddingBatch: ...

    def embed_text(
        self,
        text: str,
        *,
        request_id: str,
        task: str = "retrieve",
        latency_mode: str = "balanced",
        dimensions: int | None = None,
        provider_id: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> EmbeddingVector: ...

    def health(self, provider_id: str | None = None) -> EmbeddingHealth: ...

    def preload_state(self, provider_id: str | None = None) -> EmbeddingPreloadState: ...

    def preload(
        self,
        *,
        target: str,
        entries: tuple[EmbeddingPreloadEntry, ...],
        latency_mode: str = "balanced",
        provider_id: str | None = None,
    ) -> EmbeddingPreloadState: ...

    def queue_backfill(
        self,
        *,
        target: str,
        entries: tuple[EmbeddingPreloadEntry, ...],
        latency_mode: str = "balanced",
        provider_id: str | None = None,
    ) -> EmbeddingPreloadState: ...

    def cached_vector(
        self,
        *,
        target: str,
        cache_key: str,
        dimensions: int,
        provider_id: str | None = None,
    ) -> EmbeddingVector | None: ...

    def pending_vector(
        self,
        *,
        target: str,
        cache_key: str,
        dimensions: int,
        provider_id: str | None = None,
    ) -> bool: ...

    def steady_async(self, provider_id: str | None = None) -> bool: ...


class InMemoryEmbeddingModelRegistry:
    def __init__(self, providers: tuple[EmbeddingProvider, ...] = ()) -> None:
        self._providers: dict[str, EmbeddingProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: EmbeddingProvider) -> None:
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> EmbeddingProvider | None:
        return self._providers.get(provider_id)

    def default(self) -> EmbeddingProvider:
        provider = self.get(ELEPHANT_EMBED_PROVIDER_ID)
        if provider is not None:
            return provider
        if self._providers:
            return next(iter(self._providers.values()))
        raise LookupError("no embedding provider registered")

    def list(self) -> tuple[EmbeddingProvider, ...]:
        return tuple(self._providers.values())


class SentenceTransformerEmbeddingProvider:
    """Canonical local embedding provider backed by the shared `elephant-embed` root."""

    def __init__(
        self,
        *,
        provider_id: str = ELEPHANT_EMBED_PROVIDER_ID,
        model_id: str = ELEPHANT_EMBED_MODEL_ID,
        source_url: str = ELEPHANT_EMBED_SOURCE_URL,
        model_root: str = ELEPHANT_EMBED_MODEL_ROOT,
        supported_dimensions: tuple[int, ...] = ELEPHANT_EMBED_ONLINE_DIMENSIONS,
    ) -> None:
        self.provider_id = provider_id
        self.model_id = model_id
        self.source_url = source_url
        self.model_root = model_root
        self.supported_dimensions = tuple(dict.fromkeys(supported_dimensions))
        self._model: Any | None = None
        self._model_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._cache: dict[int, dict[tuple[str, str], EmbeddingVector]] = {}
        self._queued_entries: dict[tuple[str, int], dict[str, EmbeddingPreloadEntry]] = {}
        self._inflight_entries: dict[tuple[str, int], set[str]] = {}
        self._workers: dict[tuple[str, int], threading.Thread] = {}
        self._ready_targets_by_dimension: dict[int, set[str]] = {}
        self._failure_by_target: dict[tuple[str, int], tuple[str, datetime]] = {}
        self._preload_updated_at = _utc_now()
        self._steady_lock = threading.Lock()
        self._steady_thread: threading.Thread | None = None

    def _runtime_state(self) -> str:
        with self._steady_lock:
            worker = self._steady_thread
            if self._model is not None:
                return "loaded"
            if worker is not None and worker.is_alive():
                return "steadying"
        return "cold"

    def _health_status(self) -> tuple[str, str]:
        dependencies_ready = sentence_transformers_dependencies_ready()
        root_healthy = embedding_root_is_healthy(self.model_root)
        if not dependencies_ready:
            if root_healthy:
                return (
                    "pending",
                    "local embedding root is present, but minimal sentence-transformers dependencies still need installation.",
                )
            return (
                "pending",
                "minimal sentence-transformers dependencies are not installed yet for the local embedding path.",
            )
        if root_healthy:
            return (
                "ready",
                f"local embedding root is available at {embedding_model_root_path(self.model_root)}",
            )
        return (
            "downloading",
            f"sentence-transformers dependencies are ready; waiting for the local embedding root at {embedding_model_root_path(self.model_root)} to finish downloading.",
        )

    def _ensure_ready(self) -> None:
        status, summary = self._health_status()
        if status != "ready":
            raise RuntimeError(summary)

    def _load_model(self) -> Any:
        self._ensure_ready()
        with self._model_lock:
            if self._model is None:
                # Keep Hugging Face tokenizers and sentence-transformers from emitting
                # compatibility warnings into the interactive TUI while the local embedder steadys.
                os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
                _suppress_local_embedding_load_warnings(self.model_root)
                _patch_unsupported_torch_compile()
                from sentence_transformers import SentenceTransformer

                _model_path = str(embedding_model_root_path(self.model_root))
                # sentence-transformers 5.x renamed tokenizer_kwargs → processor_kwargs.
                # Try processor_kwargs → tokenizer_kwargs → plain load.
                import inspect as _inspect
                _st_params = set(_inspect.signature(SentenceTransformer.__init__).parameters)
                _regex_kwarg = "processor_kwargs" if "processor_kwargs" in _st_params else ("tokenizer_kwargs" if "tokenizer_kwargs" in _st_params else "")
                if _regex_kwarg:
                    try:
                        self._model = SentenceTransformer(_model_path, local_files_only=True, **{_regex_kwarg: {"fix_mistral_regex": True}})
                    except (TypeError, ValueError):
                        self._model = SentenceTransformer(_model_path, local_files_only=True)
                else:
                    self._model = SentenceTransformer(_model_path, local_files_only=True)
            return self._model

    def _encode_texts(self, texts: tuple[str, ...], *, dimensions: int) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        model = self._load_model()
        batch_size = max(1, min(len(texts), _DEFAULT_EMBED_BATCH_SIZE))
        encoded = model.encode(
            list(texts),
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=False,
            truncate_dim=dimensions,
        )
        encoded_rows = _encoded_embedding_rows(encoded)
        vectors = tuple(
            _truncate_matryoshka_vector(tuple(float(value) for value in row), dimensions=dimensions)
            for row in encoded_rows
        )
        if len(vectors) != len(texts):
            raise RuntimeError("sentence-transformers returned an unexpected embedding batch size")
        return vectors

    def _cache_key(self, *, target: str, cache_key: str) -> tuple[str, str]:
        return (_normalize_target(target), str(cache_key).strip())

    def _remember_vectors(
        self,
        *,
        target: str,
        entries: tuple[EmbeddingPreloadEntry, ...],
        dimensions: int,
        vectors: tuple[tuple[float, ...], ...],
    ) -> None:
        normalized_target = _normalize_target(target)
        with self._cache_lock:
            bucket = self._cache.setdefault(dimensions, {})
            for index, (entry, values) in enumerate(zip(entries, vectors, strict=True)):
                bucket[self._cache_key(target=normalized_target, cache_key=entry.cache_key)] = EmbeddingVector(
                    text_index=index,
                    provider_id=self.provider_id,
                    model_id=self.model_id,
                    dimensions=dimensions,
                    values=values,
                    source_text=entry.text,
                )
            self._ready_targets_by_dimension.setdefault(dimensions, set()).add(normalized_target)
            self._failure_by_target.pop((normalized_target, dimensions), None)
            self._preload_updated_at = _utc_now()

    def _prune_expired_failures_locked(self) -> None:
        current = _utc_now()
        expired = [
            worker_key
            for worker_key, (_message, retry_at) in self._failure_by_target.items()
            if retry_at <= current
        ]
        for worker_key in expired:
            self._failure_by_target.pop(worker_key, None)

    def _has_cached_vector_locked(self, *, target: str, cache_key: str, dimensions: int) -> bool:
        resolved_cache_key = self._cache_key(target=target, cache_key=cache_key)
        exact = self._cache.get(dimensions, {}).get(resolved_cache_key)
        if exact is not None:
            return True
        for available_dimensions in sorted(self._cache):
            if available_dimensions <= dimensions:
                continue
            if resolved_cache_key in self._cache.get(available_dimensions, {}):
                return True
        return False

    def _is_pending_locked(self, *, target: str, cache_key: str, dimensions: int) -> bool:
        normalized_target = _normalize_target(target)
        resolved_cache_key = str(cache_key).strip()
        for (pending_target, pending_dimensions), bucket in self._queued_entries.items():
            if pending_target != normalized_target or pending_dimensions < dimensions:
                continue
            if resolved_cache_key in bucket:
                return True
        for (pending_target, pending_dimensions), inflight in self._inflight_entries.items():
            if pending_target != normalized_target or pending_dimensions < dimensions:
                continue
            if resolved_cache_key in inflight:
                return True
        return False

    def _sync_preload(
        self,
        *,
        target: str,
        entries: tuple[EmbeddingPreloadEntry, ...],
        dimensions: int,
    ) -> EmbeddingPreloadState:
        if not entries:
            return self.preload_state()
        vectors = self._encode_texts(tuple(entry.text for entry in entries), dimensions=dimensions)
        self._remember_vectors(target=target, entries=entries, dimensions=dimensions, vectors=vectors)
        return self.preload_state()

    def _spawn_backfill_worker(self, *, target: str, dimensions: int) -> None:
        worker_key = (_normalize_target(target), dimensions)
        worker = threading.Thread(
            target=self._run_backfill_worker,
            args=worker_key,
            name=f"elephant-embed-{worker_key[0]}-{dimensions}",
            daemon=True,
        )
        self._workers[worker_key] = worker
        worker.start()

    def _run_backfill_worker(self, target: str, dimensions: int) -> None:
        worker_key = (target, dimensions)
        try:
            while True:
                with self._cache_lock:
                    self._prune_expired_failures_locked()
                    pending = tuple(self._queued_entries.get(worker_key, {}).values())
                    self._queued_entries[worker_key] = {}
                    if pending:
                        self._inflight_entries[worker_key] = {entry.cache_key for entry in pending}
                    else:
                        self._inflight_entries.pop(worker_key, None)
                if not pending:
                    break
                try:
                    self._sync_preload(target=target, entries=pending, dimensions=dimensions)
                finally:
                    with self._cache_lock:
                        self._inflight_entries.pop(worker_key, None)
        except Exception as error:
            with self._cache_lock:
                self._failure_by_target[worker_key] = (
                    str(error).strip() or error.__class__.__name__,
                    _utc_now() + _DEFAULT_BACKFILL_FAILURE_COOLDOWN,
                )
                self._preload_updated_at = _utc_now()
        finally:
            with self._cache_lock:
                self._workers.pop(worker_key, None)
                self._inflight_entries.pop(worker_key, None)
                self._preload_updated_at = _utc_now()

    def embed(self, request: EmbeddingRequest) -> EmbeddingBatch:
        dimensions = request.resolved_dimensions()
        if dimensions not in self.supported_dimensions:
            raise ValueError(
                f"provider {self.provider_id} does not support dimensions {dimensions}; "
                f"expected one of {self.supported_dimensions}"
            )
        vectors = tuple(
            EmbeddingVector(
                text_index=index,
                provider_id=self.provider_id,
                model_id=self.model_id,
                dimensions=dimensions,
                values=values,
                source_text=text,
            )
            for index, (text, values) in enumerate(
                zip(request.texts, self._encode_texts(request.texts, dimensions=dimensions), strict=True)
            )
        )
        return EmbeddingBatch(
            request_id=request.request_id,
            provider_id=self.provider_id,
            model_id=self.model_id,
            dimensions=dimensions,
            vectors=vectors,
            task=request.task,
            latency_mode=request.latency_mode,
            metadata={
                "runtime": "sentence-transformers-local",
                **{str(key): str(value) for key, value in request.metadata.items()},
            },
        )

    def health(self) -> EmbeddingHealth:
        status, summary = self._health_status()
        runtime_state = self._runtime_state()
        with self._cache_lock:
            self._prune_expired_failures_locked()
            failures = tuple(
                f"{target}:{dimensions}d"
                for (target, dimensions) in sorted(self._failure_by_target)
            )
            ready_dimensions = tuple(sorted(self._ready_targets_by_dimension))
        if status == "ready":
            if runtime_state == "steadying":
                summary = f"{summary}; model steadyup is in progress in the background"
            elif runtime_state == "loaded":
                summary = f"{summary}; model weights are already steady in memory"
            else:
                summary = f"{summary}; model weights have not been steadyed into memory yet"
        return EmbeddingHealth(
            provider_id=self.provider_id,
            model_id=self.model_id,
            status=status,
            summary=summary,
            supported_dimensions=self.supported_dimensions,
            source_url=self.source_url,
            model_root=self.model_root,
            metadata={
                "runtime": "sentence-transformers-local",
                "dependencies_ready": str(sentence_transformers_dependencies_ready()).lower(),
                "root_healthy": str(embedding_root_is_healthy(self.model_root)).lower(),
                "runtime_state": runtime_state,
                "ready_dimensions": ",".join(str(value) for value in ready_dimensions),
                "failed_targets": ",".join(failures),
            },
        )

    def preload_state(self) -> EmbeddingPreloadState:
        health = self.health()
        with self._cache_lock:
            self._prune_expired_failures_locked()
            active_workers = {key for key, worker in self._workers.items() if worker.is_alive()}
            queued = {
                key: value
                for key, value in self._queued_entries.items()
                if value
            }
            pending_targets = {
                target
                for target, _dimensions in (*active_workers, *queued.keys())
            }
            ready_targets = set().union(*self._ready_targets_by_dimension.values()) if self._ready_targets_by_dimension else set()
            pending_targets.update(target for target in _DEFAULT_PRELOAD_TARGETS if target not in ready_targets)
            ready_dimensions = tuple(sorted(self._ready_targets_by_dimension))
            failures = tuple(sorted(self._failure_by_target.items()))
            updated_at = self._preload_updated_at
        if health.status != "ready":
            return EmbeddingPreloadState(
                provider_id=self.provider_id,
                model_id=self.model_id,
                status="idle",
                summary="preload waits for the local elephant-embed runtime to become ready before candidate corpora are steadyed.",
                ready_dimensions=ready_dimensions,
                pending_targets=tuple(sorted(pending_targets)),
                updated_at=updated_at,
            )
        if failures:
            (target, dimensions), (message, retry_at) = failures[0]
            cooldown_seconds = max(0, int((retry_at - _utc_now()).total_seconds()))
            summary = f"background backfill failed while steadying {target}:{dimensions}d: {message}"
            if cooldown_seconds > 0:
                summary += f"; cooldown active for ~{cooldown_seconds}s before retry"
            return EmbeddingPreloadState(
                provider_id=self.provider_id,
                model_id=self.model_id,
                status="failed",
                summary=summary,
                ready_dimensions=ready_dimensions,
                pending_targets=tuple(sorted(pending_targets)),
                updated_at=updated_at,
            )
        if active_workers or queued:
            steadying = ", ".join(sorted(pending_targets)) or "candidate corpora"
            return EmbeddingPreloadState(
                provider_id=self.provider_id,
                model_id=self.model_id,
                status="steadying",
                summary=f"background candidate-vector steadying is active for {steadying}",
                ready_dimensions=ready_dimensions,
                pending_targets=tuple(sorted(pending_targets)),
                updated_at=updated_at,
            )
        if ready_dimensions:
            return EmbeddingPreloadState(
                provider_id=self.provider_id,
                model_id=self.model_id,
                status="ready",
                summary="preloaded candidate corpora are available through the shared elephant-embed cache",
                ready_dimensions=ready_dimensions,
                pending_targets=tuple(sorted(pending_targets)),
                updated_at=updated_at,
            )
        return EmbeddingPreloadState(
            provider_id=self.provider_id,
            model_id=self.model_id,
            status="idle",
            summary="no candidate corpora have been steadyed yet for the shared elephant-embed cache",
            ready_dimensions=(),
            pending_targets=tuple(sorted(pending_targets)),
            updated_at=updated_at,
        )

    def preload(
        self,
        *,
        target: str,
        entries: tuple[EmbeddingPreloadEntry, ...],
        latency_mode: str = "balanced",
    ) -> EmbeddingPreloadState:
        dimensions = resolve_embedding_dimensions(latency_mode)
        if self.health().status != "ready":
            return self.preload_state()
        return self._sync_preload(
            target=_normalize_target(target),
            entries=entries,
            dimensions=dimensions,
        )

    def queue_backfill(
        self,
        *,
        target: str,
        entries: tuple[EmbeddingPreloadEntry, ...],
        latency_mode: str = "balanced",
    ) -> EmbeddingPreloadState:
        dimensions = resolve_embedding_dimensions(latency_mode)
        normalized_target = _normalize_target(target)
        worker_key = (normalized_target, dimensions)
        if entries:
            with self._cache_lock:
                self._prune_expired_failures_locked()
                bucket = self._queued_entries.setdefault(worker_key, {})
                for entry in entries:
                    if not entry.cache_key.strip() or not entry.text.strip():
                        continue
                    if self._has_cached_vector_locked(
                        target=normalized_target,
                        cache_key=entry.cache_key,
                        dimensions=dimensions,
                    ):
                        continue
                    if self._is_pending_locked(
                        target=normalized_target,
                        cache_key=entry.cache_key,
                        dimensions=dimensions,
                    ):
                        continue
                    bucket[entry.cache_key] = entry
                if not bucket:
                    self._queued_entries.pop(worker_key, None)
                self._preload_updated_at = _utc_now()
        if self.health().status != "ready":
            return self.preload_state()
        cooldown_active = False
        with self._cache_lock:
            self._prune_expired_failures_locked()
            if worker_key in self._failure_by_target:
                cooldown_active = True
                needs_spawn = False
            else:
                worker = self._workers.get(worker_key)
                needs_spawn = bool(self._queued_entries.get(worker_key)) and (worker is None or not worker.is_alive())
            if needs_spawn:
                self._spawn_backfill_worker(target=normalized_target, dimensions=dimensions)
        if cooldown_active:
            return self.preload_state()
        return self.preload_state()

    def _run_steady_worker(self) -> None:
        try:
            self._load_model()
        except Exception:
            # Health already describes why the provider is not ready. Later steady
            # attempts or real embedding requests can retry once the runtime recovers.
            LOGGER.warning("local embedding steady worker failed to load model", exc_info=True)
            return
        finally:
            with self._steady_lock:
                self._steady_thread = None

    def steady_async(self) -> bool:
        if self.health().status != "ready":
            return False
        with self._steady_lock:
            if self._model is not None:
                return False
            if self._steady_thread is not None and self._steady_thread.is_alive():
                return False
            worker = threading.Thread(
                target=self._run_steady_worker,
                name="elephant-embed-model-steady",
                daemon=True,
            )
            self._steady_thread = worker
            worker.start()
            return True

    def cached_vector(self, *, target: str, cache_key: str, dimensions: int) -> EmbeddingVector | None:
        resolved_dimensions = resolve_embedding_dimensions(dimensions=dimensions)
        normalized_target = _normalize_target(target)
        resolved_cache_key = self._cache_key(target=normalized_target, cache_key=cache_key)
        with self._cache_lock:
            exact = self._cache.get(resolved_dimensions, {}).get(resolved_cache_key)
            if exact is not None:
                return exact
            for available_dimensions in sorted(self._cache):
                if available_dimensions <= resolved_dimensions:
                    continue
                source = self._cache.get(available_dimensions, {}).get(resolved_cache_key)
                if source is None:
                    continue
                derived = EmbeddingVector(
                    text_index=source.text_index,
                    provider_id=self.provider_id,
                    model_id=self.model_id,
                    dimensions=resolved_dimensions,
                    values=_truncate_matryoshka_vector(source.values, dimensions=resolved_dimensions),
                    source_text=source.source_text,
                )
                self._cache.setdefault(resolved_dimensions, {})[resolved_cache_key] = derived
                self._ready_targets_by_dimension.setdefault(resolved_dimensions, set()).add(normalized_target)
                self._preload_updated_at = _utc_now()
                return derived
        return None

    def pending_vector(self, *, target: str, cache_key: str, dimensions: int) -> bool:
        resolved_dimensions = resolve_embedding_dimensions(dimensions=dimensions)
        normalized_target = _normalize_target(target)
        with self._cache_lock:
            return self._is_pending_locked(
                target=normalized_target,
                cache_key=cache_key,
                dimensions=resolved_dimensions,
            )


class DefaultEmbeddingService:
    def __init__(
        self,
        *,
        registry: EmbeddingModelRegistry | None = None,
        default_provider_id: str = ELEPHANT_EMBED_PROVIDER_ID,
    ) -> None:
        self.registry = registry or InMemoryEmbeddingModelRegistry((SentenceTransformerEmbeddingProvider(),))
        self.default_provider_id = default_provider_id

    def _provider(self, provider_id: str | None = None) -> EmbeddingProvider:
        resolved_id = provider_id or self.default_provider_id
        provider = self.registry.get(resolved_id)
        if provider is not None:
            return provider
        if provider_id is None:
            return self.registry.default()
        raise LookupError(f"embedding provider is not registered: {provider_id}")

    def embed(self, request: EmbeddingRequest) -> EmbeddingBatch:
        return self._provider(request.provider_id).embed(request)

    def embed_text(
        self,
        text: str,
        *,
        request_id: str,
        task: str = "retrieve",
        latency_mode: str = "balanced",
        dimensions: int | None = None,
        provider_id: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> EmbeddingVector:
        resolved_provider = self._provider(provider_id)
        batch = resolved_provider.embed(
            EmbeddingRequest(
                request_id=request_id,
                texts=(text,),
                task=task,
                latency_mode=latency_mode,
                dimensions=dimensions,
                provider_id=resolved_provider.provider_id,
                model_id=resolved_provider.model_id,
                metadata={str(key): str(value) for key, value in dict(metadata or {}).items()},
            )
        )
        return batch.vectors[0]

    def health(self, provider_id: str | None = None) -> EmbeddingHealth:
        return self._provider(provider_id).health()

    def preload_state(self, provider_id: str | None = None) -> EmbeddingPreloadState:
        return self._provider(provider_id).preload_state()

    def preload(
        self,
        *,
        target: str,
        entries: tuple[EmbeddingPreloadEntry, ...],
        latency_mode: str = "balanced",
        provider_id: str | None = None,
    ) -> EmbeddingPreloadState:
        return self._provider(provider_id).preload(
            target=target,
            entries=entries,
            latency_mode=latency_mode,
        )

    def queue_backfill(
        self,
        *,
        target: str,
        entries: tuple[EmbeddingPreloadEntry, ...],
        latency_mode: str = "balanced",
        provider_id: str | None = None,
    ) -> EmbeddingPreloadState:
        return self._provider(provider_id).queue_backfill(
            target=target,
            entries=entries,
            latency_mode=latency_mode,
        )

    def cached_vector(
        self,
        *,
        target: str,
        cache_key: str,
        dimensions: int,
        provider_id: str | None = None,
    ) -> EmbeddingVector | None:
        return self._provider(provider_id).cached_vector(
            target=target,
            cache_key=cache_key,
            dimensions=dimensions,
        )

    def pending_vector(
        self,
        *,
        target: str,
        cache_key: str,
        dimensions: int,
        provider_id: str | None = None,
    ) -> bool:
        pending = getattr(self._provider(provider_id), "pending_vector", None)
        if not callable(pending):
            return False
        return bool(
            pending(
                target=target,
                cache_key=cache_key,
                dimensions=dimensions,
            )
        )

    def steady_async(self, provider_id: str | None = None) -> bool:
        provider = self._provider(provider_id)
        steady = getattr(provider, "steady_async", None)
        if not callable(steady):
            return False
        return bool(steady())
