"""Unit tests for packages.tools.handler_support pure utilities."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.tools.handler_support import (
    coerce_bool,
    coerce_choices,
    coerce_env,
    coerce_int,
    coerce_optional_bool,
    join_parts,
    normalized_url,
    optional_string,
    resolve_allowed_path,
    tool_summary,
    truncate,
)
from packages.tools.runtime import ToolInvocation, ToolRuntimeContext


class TestCoerceBool(unittest.TestCase):
    def test_none_returns_default(self) -> None:
        self.assertIs(coerce_bool(None, default=True), True)
        self.assertIs(coerce_bool(None, default=False), False)

    def test_bool_passthrough(self) -> None:
        self.assertIs(coerce_bool(True, default=False), True)
        self.assertIs(coerce_bool(False, default=True), False)

    def test_truthy_strings(self) -> None:
        for value in ("1", "true", "True", "TRUE", "yes", "YES", "on", "ON"):
            with self.subTest(value=value):
                self.assertIs(coerce_bool(value, default=False), True)

    def test_falsy_strings(self) -> None:
        for value in ("0", "false", "no", "off", "maybe", "2", ""):
            with self.subTest(value=value):
                self.assertIs(coerce_bool(value, default=True), False)

    def test_int_coerced(self) -> None:
        self.assertIs(coerce_bool(1, default=False), True)
        self.assertIs(coerce_bool(0, default=True), False)


class TestCoerceOptionalBool(unittest.TestCase):
    def test_none_returns_none(self) -> None:
        self.assertIsNone(coerce_optional_bool(None))

    def test_bool_passthrough(self) -> None:
        self.assertIs(coerce_optional_bool(True), True)
        self.assertIs(coerce_optional_bool(False), False)

    def test_truthy_strings(self) -> None:
        for value in ("true", "1", "yes", "on"):
            with self.subTest(value=value):
                self.assertIs(coerce_optional_bool(value), True)

    def test_falsy_strings(self) -> None:
        for value in ("false", "0", "no", "off"):
            with self.subTest(value=value):
                self.assertIs(coerce_optional_bool(value), False)

    def test_unrecognized_returns_none(self) -> None:
        self.assertIsNone(coerce_optional_bool("maybe"))
        self.assertIsNone(coerce_optional_bool("2"))


class TestCoerceInt(unittest.TestCase):
    def test_none_returns_default(self) -> None:
        self.assertEqual(coerce_int(None, default=42), 42)

    def test_valid_int(self) -> None:
        self.assertEqual(coerce_int("10", default=0), 10)
        self.assertEqual(coerce_int(10, default=0), 10)

    def test_invalid_returns_default(self) -> None:
        self.assertEqual(coerce_int("abc", default=5), 5)
        self.assertEqual(coerce_int([], default=5), 5)

    def test_float_truncated(self) -> None:
        self.assertEqual(coerce_int(3.7, default=0), 3)


class TestCoerceEnv(unittest.TestCase):
    def test_non_mapping_returns_empty(self) -> None:
        self.assertEqual(coerce_env("not a mapping"), {})
        self.assertEqual(coerce_env(None), {})
        self.assertEqual(coerce_env([("a", 1)]), {})

    def test_mapping_coerced_to_str_values(self) -> None:
        self.assertEqual(coerce_env({"A": 1, "B": True}), {"A": "1", "B": "True"})

    def test_empty_mapping(self) -> None:
        self.assertEqual(coerce_env({}), {})


class TestCoerceChoices(unittest.TestCase):
    def test_none_returns_empty(self) -> None:
        self.assertEqual(coerce_choices(None), ())

    def test_pipe_separated_string(self) -> None:
        self.assertEqual(coerce_choices("a | b | c"), ("a", "b", "c"))

    def test_list_input(self) -> None:
        self.assertEqual(coerce_choices(["a", "b", "c"]), ("a", "b", "c"))

    def test_tuple_input(self) -> None:
        self.assertEqual(coerce_choices(("x", "y")), ("x", "y"))

    def test_strips_whitespace(self) -> None:
        self.assertEqual(coerce_choices(" a | b "), ("a", "b"))
        self.assertEqual(coerce_choices([" a ", " b "]), ("a", "b"))

    def test_filters_empty(self) -> None:
        self.assertEqual(coerce_choices("a || b"), ("a", "b"))
        self.assertEqual(coerce_choices(["a", "", "b"]), ("a", "b"))

    def test_other_type_returns_empty(self) -> None:
        self.assertEqual(coerce_choices(42), ())


class TestOptionalString(unittest.TestCase):
    def test_none_returns_none(self) -> None:
        self.assertIsNone(optional_string(None))

    def test_whitespace_returns_none(self) -> None:
        self.assertIsNone(optional_string("   "))

    def test_valid_string_trimmed(self) -> None:
        self.assertEqual(optional_string("  hello  "), "hello")

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(optional_string(""))


class TestTruncate(unittest.TestCase):
    def test_short_string_unchanged(self) -> None:
        self.assertEqual(truncate("hello"), "hello")

    def test_exactly_at_limit(self) -> None:
        text = "a" * 1200
        self.assertEqual(truncate(text), text)

    def test_over_limit_truncated(self) -> None:
        text = "a" * 1300
        result = truncate(text)
        self.assertLessEqual(len(result), 1200)
        self.assertTrue(result.endswith("…"))

    def test_custom_limit(self) -> None:
        text = "a" * 100
        result = truncate(text, limit=50)
        self.assertTrue(result.endswith("…"))
        self.assertLessEqual(len(result), 50)

    def test_strips_whitespace(self) -> None:
        self.assertEqual(truncate("  hello  "), "hello")


class TestJoinParts(unittest.TestCase):
    def test_empty_parts(self) -> None:
        self.assertEqual(join_parts(), "")

    def test_single_part(self) -> None:
        self.assertEqual(join_parts("hello"), "hello")

    def test_multiple_parts(self) -> None:
        self.assertEqual(join_parts("a", "b", "c"), "a\nb\nc")

    def test_skips_empty(self) -> None:
        self.assertEqual(join_parts("a", "", "b"), "a\nb")

    def test_strips_whitespace(self) -> None:
        self.assertEqual(join_parts("  a  ", "  b  "), "a\nb")


class TestNormalizedUrl(unittest.TestCase):
    def test_valid_url(self) -> None:
        self.assertEqual(normalized_url("https://example.com"), "https://example.com")

    def test_adds_https_scheme(self) -> None:
        self.assertEqual(normalized_url("example.com"), "https://example.com")

    def test_http_scheme(self) -> None:
        self.assertEqual(normalized_url("http://example.com"), "http://example.com")

    def test_strips_quotes(self) -> None:
        self.assertEqual(normalized_url('"https://example.com"'), "https://example.com")
        self.assertEqual(normalized_url("'https://example.com'"), "https://example.com")

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(normalized_url(""))
        self.assertIsNone(normalized_url("   "))

    def test_bad_scheme_returns_none(self) -> None:
        self.assertIsNone(normalized_url("ftp://example.com"))

    def test_no_netloc_returns_none(self) -> None:
        self.assertIsNone(normalized_url("https://"))


class TestResolveAllowedPath(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def test_none_returns_root(self) -> None:
        result = resolve_allowed_path(self.root, None, must_exist=False)
        self.assertEqual(result, self.root.resolve())

    def test_relative_path_resolved(self) -> None:
        result = resolve_allowed_path(self.root, "subdir", must_exist=False)
        self.assertEqual(result, (self.root / "subdir").resolve())

    def test_absolute_path_under_root(self) -> None:
        target = self.root / "subdir"
        result = resolve_allowed_path(self.root, str(target), must_exist=False)
        self.assertEqual(result, target.resolve())

    def test_path_traversal_blocked(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_allowed_path(self.root, "../../etc/passwd", must_exist=False)
        self.assertIn("outside the allowed roots", str(ctx.exception))

    def test_must_exist_raises_for_missing(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_allowed_path(self.root, "nonexistent", must_exist=True)
        self.assertIn("does not exist", str(ctx.exception))

    def test_must_exist_succeeds_for_existing(self) -> None:
        existing = self.root / "existing_file"
        existing.touch()
        result = resolve_allowed_path(self.root, "existing_file", must_exist=True)
        self.assertEqual(result, existing.resolve())

    def test_allowed_roots_permits_access(self) -> None:
        other_tmpdir = tempfile.mkdtemp()
        other_root = Path(other_tmpdir)
        result = resolve_allowed_path(
            self.root, str(other_root / "file.txt"),
            must_exist=False, allowed_roots=(other_root,),
        )
        self.assertEqual(result, (other_root / "file.txt").resolve())

    def test_fallback_to_trusted_root(self) -> None:
        # Create a file in allowed_roots, not in primary root
        other_tmpdir = tempfile.mkdtemp()
        other_root = Path(other_tmpdir)
        (other_root / "test_file.py").touch()
        result = resolve_allowed_path(
            self.root, "test_file.py",
            must_exist=True, allowed_roots=(other_root,),
        )
        self.assertEqual(result, (other_root / "test_file.py").resolve())


class TestToolSummary(unittest.TestCase):
    def test_returns_expected_keys(self) -> None:
        context = ToolRuntimeContext(cwd=Path.cwd())
        invocation = ToolInvocation(
            invocation_id="inv-1",
            tool_id="test.tool",
            session_id="sess-1",
            context=context,
        )
        result = tool_summary(invocation, "did something")
        self.assertEqual(result["execution_id"], "inv-1")
        self.assertEqual(result["summary"], "did something")
        self.assertEqual(result["outcome"], "success")
        self.assertEqual(result["side_effects"], ("tool",))

    def test_custom_side_effects_and_outcome(self) -> None:
        context = ToolRuntimeContext(cwd=Path.cwd())
        invocation = ToolInvocation(
            invocation_id="inv-2",
            tool_id="test.tool",
            session_id="sess-2",
            context=context,
        )
        result = tool_summary(
            invocation, "error occurred",
            side_effects=("network",), outcome="error",
        )
        self.assertEqual(result["outcome"], "error")
        self.assertEqual(result["side_effects"], ("network",))


if __name__ == "__main__":
    unittest.main()
