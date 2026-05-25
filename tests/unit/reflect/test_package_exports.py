from __future__ import annotations

import unittest

import packages.reflect as reflect
from packages.reflect import detect_outdated_patterns, detect_skill_gaps


class ReflectPackageExportsTest(unittest.TestCase):
    def test_all_declared_exports_are_bound(self) -> None:
        missing = [name for name in reflect.__all__ if not hasattr(reflect, name)]

        self.assertEqual(missing, [])

    def test_skill_signal_helpers_are_importable_from_package_root(self) -> None:
        self.assertIs(detect_skill_gaps, reflect.detect_skill_gaps)
        self.assertIs(detect_outdated_patterns, reflect.detect_outdated_patterns)


if __name__ == "__main__":
    unittest.main()
