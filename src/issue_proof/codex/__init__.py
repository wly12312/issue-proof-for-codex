"""Optional, offline Codex maintenance evidence adapters.

The package never launches Codex or reads Codex's private state.  It consumes only an
explicitly supplied trace and turns the small public event vocabulary into a conservative
maintenance receipt.
"""

from .claims import CLAIM_TYPES, Claim, verify_claims
from .events import TraceSummary
from .parser import ParseLimits, parse_trace
from .receipt import RECEIPT_SCHEMA_VERSION, CodexMaintenanceReceipt

__all__ = [
    "CLAIM_TYPES",
    "Claim",
    "CodexMaintenanceReceipt",
    "ParseLimits",
    "RECEIPT_SCHEMA_VERSION",
    "TraceSummary",
    "parse_trace",
    "verify_claims",
]
