"""Deploy e2e tests."""

from __future__ import annotations

import unittest


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str | None) -> unittest.TestSuite:
    return loader.discover(start_dir=__path__[0], pattern="test_*.py")
