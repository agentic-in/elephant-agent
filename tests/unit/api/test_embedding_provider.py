from __future__ import annotations

from apps.api import api_runtime_provider_methods


class _Runtime:
    def __init__(self) -> None:
        self.local_source = None
        self.force_download = None

    def set_local_embedding_provider(self, *, source: str | None = None, force_download: bool = False):
        self.local_source = source
        self.force_download = force_download
        return {"source": "local-default", "embedding_bootstrap_source": source}


def test_set_embedding_provider_passes_local_model_source_and_redownload_flag() -> None:
    runtime = _Runtime()

    result = api_runtime_provider_methods.set_embedding_provider(
        runtime,
        {
            "source": "local",
            "modelSource": "modelscope",
            "forceDownload": True,
        },
    )

    assert runtime.local_source == "modelscope"
    assert runtime.force_download is True
    assert result["embedding_provider"]["embedding_bootstrap_source"] == "modelscope"


def test_set_embedding_provider_defaults_invalid_local_source_without_redownload() -> None:
    runtime = _Runtime()

    api_runtime_provider_methods.set_embedding_provider(
        runtime,
        {
            "source": "elephant-embed",
            "modelSource": "unknown",
            "forceDownload": "false",
        },
    )

    assert runtime.local_source is None
    assert runtime.force_download is False
