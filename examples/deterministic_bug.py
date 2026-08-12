"""Small deterministic fixture used by the manual CLI walkthrough."""

import sys
from pathlib import Path

marker = Path(".issue-proof/manual-run/fixed.marker")
sys.exit(0 if marker.exists() else 1)
