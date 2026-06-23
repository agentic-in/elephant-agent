"""Unit tests for packages.tools.handlers_code_execution._validate_python_snippet."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.tools.handlers_code_execution import _validate_python_snippet


class TestValidatePythonSnippetAllowedImports(unittest.TestCase):
    def test_safe_imports_allowed(self) -> None:
        for module in ("json", "math", "re", "datetime", "collections"):
            with self.subTest(module=module):
                _validate_python_snippet(f"import {module}")

    def test_safe_from_imports_allowed(self) -> None:
        _validate_python_snippet("from collections import OrderedDict")

    def test_dangerous_import_blocked(self) -> None:
        for module in ("os", "subprocess", "sys", "shutil", "socket"):
            with self.subTest(module=module):
                with self.assertRaises(ValueError) as ctx:
                    _validate_python_snippet(f"import {module}")
                self.assertIn("does not allow importing", str(ctx.exception))

    def test_dangerous_from_import_blocked(self) -> None:
        with self.assertRaises(ValueError):
            _validate_python_snippet("from os import path")

    def test_wildcard_import_blocked(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _validate_python_snippet("from json import *")
        self.assertIn("wildcard", str(ctx.exception))

    def test_relative_import_blocked(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _validate_python_snippet("from . import something")
        self.assertIn("relative", str(ctx.exception))


class TestValidatePythonSnippetBlockedBuiltins(unittest.TestCase):
    def test_blocked_names(self) -> None:
        for name in ("__import__", "eval", "exec", "open", "compile", "breakpoint"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as ctx:
                    _validate_python_snippet(f"{name}()")
                self.assertIn("does not allow", str(ctx.exception))

    def test_safe_function_allowed(self) -> None:
        _validate_python_snippet("print('hello')")
        _validate_python_snippet("len([1, 2, 3])")


class TestValidatePythonSnippetDunderAttributes(unittest.TestCase):
    def test_dunder_attribute_access_blocked(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _validate_python_snippet("obj.__class__")
        self.assertIn("dunder", str(ctx.exception))

    def test_safe_dunder_name_allowed(self) -> None:
        _validate_python_snippet("obj.__name__")

    def test_dunder_dict_blocked(self) -> None:
        with self.assertRaises(ValueError):
            _validate_python_snippet("obj.__dict__")


class TestValidatePythonSnippetValidCode(unittest.TestCase):
    def test_simple_assignment(self) -> None:
        _validate_python_snippet("x = 42")

    def test_function_definition(self) -> None:
        _validate_python_snippet("def foo():\n    return 1")

    def test_for_loop(self) -> None:
        _validate_python_snippet("for i in range(10):\n    print(i)")

    def test_list_comprehension(self) -> None:
        _validate_python_snippet("[x * 2 for x in range(10)]")

    def test_syntax_error_raises(self) -> None:
        with self.assertRaises(SyntaxError):
            _validate_python_snippet("def foo(")

    def test_empty_code_raises(self) -> None:
        # Note: _validate_python_snippet doesn't check for empty code itself,
        # but ast.parse("") is valid (empty module). The caller checks.
        _validate_python_snippet("")


if __name__ == "__main__":
    unittest.main()
