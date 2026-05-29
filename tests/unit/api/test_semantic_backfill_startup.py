from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from apps.api import api_runtime_impl


def test_semantic_backfill_starts_background_worker() -> None:
    repository = SimpleNamespace()
    indexer = SimpleNamespace()

    with (
        mock.patch.object(api_runtime_impl, "backfill_existing_semantic_summaries") as backfill,
        mock.patch.object(api_runtime_impl, "Thread") as thread_class,
    ):
        thread = thread_class.return_value
        started = api_runtime_impl._backfill_semantic_summaries_async(repository, indexer)
        thread_class.call_args.kwargs["target"]()

    assert started
    thread.start.assert_called_once_with()
    backfill.assert_called_once_with(repository=repository, indexer=indexer)
