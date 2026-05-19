from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.tools import render_builtin_tool_summary_markdown


def _extract_between_markers(text: str, begin: str, end: str) -> str:
    start = text.index(begin) + len(begin)
    finish = text.index(end)
    return text[start:finish].strip()


class BuiltinCatalogDocsTest(unittest.TestCase):
    def test_site_tools_doc_stays_in_sync_with_runtime_summary(self) -> None:
        """apps/site/docs/capacities/tools.md carries the summary block."""
        docs_path = ROOT / "apps" / "site" / "docs" / "capacities" / "tools.md"
        rendered = render_builtin_tool_summary_markdown().strip()
        actual = _extract_between_markers(
            docs_path.read_text(encoding="utf-8"),
            "<!-- BEGIN:GENERATED_BUILTIN_TOOL_SUMMARY -->",
            "<!-- END:GENERATED_BUILTIN_TOOL_SUMMARY -->",
        )
        self.assertEqual(actual, rendered)

    def test_cli_reference_builtin_tool_summary_stays_in_sync_with_runtime_catalog(
        self,
    ) -> None:
        docs_path = ROOT / "apps" / "site" / "docs" / "reference" / "cli.md"
        rendered = render_builtin_tool_summary_markdown().strip()
        actual = _extract_between_markers(
            docs_path.read_text(encoding="utf-8"),
            "<!-- BEGIN:GENERATED_BUILTIN_TOOL_SUMMARY -->",
            "<!-- END:GENERATED_BUILTIN_TOOL_SUMMARY -->",
        )
        self.assertEqual(actual, rendered)


if __name__ == "__main__":
    unittest.main()
