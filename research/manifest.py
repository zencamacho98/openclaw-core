# research/manifest.py
#
# ExperimentManifest: the structured contract for a single bounded experiment.
#
# Every experiment in the autonomous research loop must be described by a
# manifest before it runs. The manifest is the unit of governance — it carries
# the experiment class, hypothesis, approved param ranges, and status.
#
# Manifests are pure data (no side effects). Validation lives in governance.py.

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ExperimentManifest:
    experiment_id: str                      # e.g. "batch_20260409T120000_001"
    batch_id: str                           # groups experiments in the same run
    experiment_class: str                   # profit_taking | entry_quality | loss_structure
    hypothesis: str                         # plain-English explanation of what is being tested
    mutated_params: dict[str, Any]          # {param_name: new_value}
    approved_ranges: dict[str, list[float]] # {param_name: [min, max]} — recorded for audit
    seed_set: list[int]                     # seeds used for this experiment
    tick_sizes: list[int]                   # tick lengths used for this experiment
    status: str = "pending"                 # pending | running | complete | failed
    output_path: str | None = None          # path to the saved validation record JSON
    summary: dict[str, Any] | None = None  # filled in after review
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExperimentManifest":
        return cls(**d)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ── ID helpers ────────────────────────────────────────────────────────────────

def make_batch_id() -> str:
    """Generate a timestamped batch ID. Stable for the duration of one run."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"batch_{ts}"


def make_experiment_id(batch_id: str, index: int) -> str:
    """Generate a per-experiment ID that sorts lexicographically within a batch."""
    return f"{batch_id}_{index:03d}"
