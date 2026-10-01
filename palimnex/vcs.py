"""Git ignore checks for local runtime state; no repository writes."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

GIT_TIMEOUT_SECONDS = 10

IgnoreState = Literal["ignored", "not_ignored", "not_applicable", "unknown"]


def git_ignore_state(root: Path, relative: str) -> IgnoreState:
    """Report whether Git ignores a repository-relative path.

    `not_applicable` means Git is unavailable or `root` is not inside a work
    tree; `unknown` means Git was available but could not answer.
    """
    try:
        inside = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "not_applicable"
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return "not_applicable"
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", "--", relative],
            capture_output=True, timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode == 0:
        return "ignored"
    if result.returncode == 1:
        return "not_ignored"
    return "unknown"
