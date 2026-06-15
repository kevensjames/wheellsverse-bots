"""SUPREMA autorepair — workspace-wide auto-healing.

Scans the six SUPREMA projects (narai, wheellsverse-bots, nexora, sol, toodle,
kdp-autopilot) for known issue patterns and applies safe fixes automatically.
Risky findings are reported for human review.

Catalog of patterns is derived from real bugs encountered while operating
the workspace — every pattern here corresponds to a fix that was actually
needed at some point. New patterns are added as new classes of bug are
discovered.
"""

__version__ = "0.1.0"
