from __future__ import annotations

import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from palimnex.core import BUNDLE_VERSION


ROOT = Path(__file__).resolve().parents[2]


class VersionTests(unittest.TestCase):
    def test_pyproject_reads_the_bundle_version_dynamically(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as source:
            configuration = tomllib.load(source)
        self.assertNotIn("version", configuration["project"])
        self.assertEqual(configuration["project"]["dynamic"], ["version"])
        self.assertEqual(
            configuration["tool"]["setuptools"]["dynamic"]["version"],
            {"attr": "palimnex.core.BUNDLE_VERSION"},
        )

    def test_cli_version_matches_the_bundle_version(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "palimnex.py"), "--version"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), BUNDLE_VERSION)


if __name__ == "__main__":
    unittest.main()
