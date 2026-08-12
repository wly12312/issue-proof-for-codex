"""Stable Skill entry point that delegates to the installed project CLI."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    command = [sys.executable, "-I", "-m", "issue_proof", *sys.argv[1:]]
    return subprocess.run(command, check=False, shell=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
