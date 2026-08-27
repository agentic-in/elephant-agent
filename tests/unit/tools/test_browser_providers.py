from __future__ import annotations

import os
import unittest
from unittest import mock

from packages.tools import browser_providers as browser_providers_module
from packages.tools.browser_providers import BrowserUseProvider


class BrowserUseProviderTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {"BROWSER_USE_API_KEY": "test-key"}, clear=True)
    @mock.patch.object(browser_providers_module, "_http_json")
    def test_default_api_uses_v4_for_browser_lifecycle(self, request: mock.Mock) -> None:
        request.return_value = {
            "id": "session-1",
            "cdpUrl": "wss://example.test/session-1",
        }

        provider = BrowserUseProvider()
        session = provider.create_session("task-1")
        provider.close_session(session.session_id)

        self.assertEqual("session-1", session.session_id)
        self.assertEqual("wss://example.test/session-1", session.cdp_url)
        self.assertEqual(
            [
                mock.call(
                    "POST",
                    "https://api.browser-use.com/api/v4/browsers",
                    headers={
                        "X-Browser-Use-API-Key": "test-key",
                        "Content-Type": "application/json",
                    },
                    payload={"timeout": 5},
                ),
                mock.call(
                    "PATCH",
                    "https://api.browser-use.com/api/v4/browsers/session-1",
                    headers={
                        "X-Browser-Use-API-Key": "test-key",
                        "Content-Type": "application/json",
                    },
                    payload={"action": "stop"},
                    tolerate_http_errors=True,
                ),
            ],
            request.call_args_list,
        )


if __name__ == "__main__":
    unittest.main()
