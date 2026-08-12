"""Stable Skill entry point that delegates to the installed project CLI."""

from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> int:
    executable = shutil.which("issue-proof")
    if not executable:
        print(
            "The installed `issue-proof` CLI was not found. Install the project package "
            "in the active environment before running this Skill.",
            file=sys.stderr,
        )
        return 127
    return subprocess.run([executable, *sys.argv[1:]], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
