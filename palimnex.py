#!/usr/bin/env python3
"""Repository-root entrypoint for the portable Palimnex bundle."""

import os
from pathlib import Path

# Preserve the copied bundle's explicit script-location root. Installed console
# entrypoints instead use their working directory (or an explicit override).
os.environ.setdefault("PALIMNEX_ROOT", str(Path(__file__).resolve().parent))

from palimnex import main

if __name__ == "__main__":
    raise SystemExit(main())
