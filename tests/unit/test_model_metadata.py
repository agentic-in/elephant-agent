from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest import mock

from packages.models import model_metadata


class _MetadataStubServer:
    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.requests: list[str] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def start(self) -> "_MetadataStubServer":
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                outer.requests.append(self.path)
                payload = outer.routes.get(self.path)
                if payload is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler


class ModelMetadataResolutionTests(unittest.TestCase):
    def test_resolves_provider_aware_models_dev_context(self) -> None:
        with mock.patch.object(
            model_metadata,
            "fetch_models_dev_registry",
            return_value={
                "openai": {
                    "models": {
                        "gpt-5.4": {
                            "limit": {
                                "context": 1_050_000,
                                "output": 32_768,
                            }
                        }
                    }
                }
            },
        ):
            metadata = model_metadata.resolve_provider_model_metadata(
                provider_id="openai",
                model_id="gpt-5.4",
                base_url="https://api.openai.com/v1",
            )

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.context_window_tokens, 1_050_000)
        self.assertEqual(metadata.max_output_tokens, 32_768)
        self.assertEqual(metadata.source, "models.dev:openai")

    def test_resolves_openrouter_metadata_when_models_dev_misses(self) -> None:
        openrouter_entry = model_metadata.ResolvedModelMetadata(
            context_window_tokens=262_144,
            max_output_tokens=16_384,
            source="openrouter",
        )
        with (
            mock.patch.object(model_metadata, "fetch_models_dev_registry", return_value={}),
            mock.patch.object(
                model_metadata,
                "fetch_openrouter_model_metadata",
                return_value={"anthropic/claude-sonnet-4.6": openrouter_entry},
            ),
        ):
            metadata = model_metadata.resolve_provider_model_metadata(
                provider_id="openrouter",
                model_id="anthropic/claude-sonnet-4.6",
                base_url="https://openrouter.ai/api/v1",
            )

        self.assertEqual(metadata, openrouter_entry)

    def test_resolves_local_endpoint_model_detail_before_remote_registries(
        self,
    ) -> None:
        server = _MetadataStubServer(
            {
                "/v1/models/local-model": {
                    "id": "local-model",
                    "max_model_len": 65_536,
                    "max_output_tokens": 8_192,
                }
            }
        ).start()
        self.addCleanup(server.close)

        with (
            mock.patch.object(model_metadata, "fetch_models_dev_registry") as models_dev,
            mock.patch.object(model_metadata, "fetch_openrouter_model_metadata") as openrouter,
        ):
            metadata = model_metadata.resolve_provider_model_metadata(
                provider_id="vllm",
                model_id="local-model",
                base_url=server.base_url,
            )

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.context_window_tokens, 65_536)
        self.assertEqual(metadata.max_output_tokens, 8_192)
        self.assertEqual(metadata.source, "local:model-detail")
        models_dev.assert_not_called()
        openrouter.assert_not_called()

    def test_resolves_openai_compatible_provider_from_known_base_url(self) -> None:
        with mock.patch.object(
            model_metadata,
            "fetch_models_dev_registry",
            return_value={
                "alibaba": {
                    "models": {
                        "qwen3-coder-plus": {
                            "limit": {
                                "context": 1_000_000,
                                "output": 65_536,
                            }
                        }
                    }
                }
            },
        ):
            metadata = model_metadata.resolve_provider_model_metadata(
                provider_id="openai-compatible",
                model_id="qwen3-coder-plus",
                base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            )

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.context_window_tokens, 1_000_000)
        self.assertEqual(metadata.source, "models.dev:alibaba")

    def test_persistent_context_length_cache_takes_precedence(self) -> None:
        with TemporaryDirectory() as tempdir:
            cache_path = Path(tempdir) / "context-length-cache.json"
            with mock.patch.dict(
                os.environ,
                {"ELEPHANT_CONTEXT_LENGTH_CACHE_PATH": str(cache_path)},
                clear=False,
            ):
                model_metadata.save_context_length(
                    "custom-model",
                    "https://example.test/v1",
                    98_304,
                )
                with (
                    mock.patch.object(model_metadata, "fetch_models_dev_registry") as models_dev,
                    mock.patch.object(model_metadata, "fetch_openrouter_model_metadata") as openrouter,
                ):
                    metadata = model_metadata.resolve_provider_model_metadata(
                        provider_id="openai-compatible",
                        model_id="custom-model",
                        base_url="https://example.test/v1",
                    )

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.context_window_tokens, 98_304)
        self.assertEqual(metadata.source, "context-length-cache")
        models_dev.assert_not_called()
        openrouter.assert_not_called()

    def test_local_probe_persists_detected_context_length(self) -> None:
        server = _MetadataStubServer(
            {
                "/v1/models/local-model": {
                    "id": "local-model",
                    "max_model_len": 65_536,
                }
            }
        ).start()
        self.addCleanup(server.close)

        with TemporaryDirectory() as tempdir:
            cache_path = Path(tempdir) / "context-length-cache.json"
            with mock.patch.dict(
                os.environ,
                {"ELEPHANT_CONTEXT_LENGTH_CACHE_PATH": str(cache_path)},
                clear=False,
            ):
                metadata = model_metadata.resolve_provider_model_metadata(
                    provider_id="vllm",
                    model_id="local-model",
                    base_url=server.base_url,
                )
                cached = model_metadata.get_cached_context_length("local-model", server.base_url)

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.context_window_tokens, 65_536)
        self.assertEqual(cached, 65_536)


if __name__ == "__main__":
    unittest.main()
