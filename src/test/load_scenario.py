"""
Load scenario data models for Gatling-style load testing.
Supports closed-model execution (maintain N concurrent virtual users).
Open-model (inject at rate) is architecturally reserved via LoadPhase.model field.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import statistics


@dataclass
class LoadPhase:
    """A single phase in a load scenario timeline."""
    type: str               # "ramp" | "steady"
    duration_s: int         # Phase duration in seconds
    from_users: int = 0     # Start concurrency (ramp only; ignored for steady)
    to_users: int = 1       # Target concurrency
    # --- Open-model reservation (not yet implemented) ---
    model: str = "closed"               # "closed" | "open"
    inject_rate_per_s: Optional[float] = None  # Reserved for open model

    def validate(self):
        if self.type not in ("ramp", "steady"):
            raise ValueError(f"Unknown phase type: {self.type!r} (use 'ramp' or 'steady')")
        if self.model == "open":
            raise NotImplementedError(
                "Open-model injection (inject_rate_per_s) is not yet implemented. Use model='closed'."
            )
        if self.duration_s <= 0:
            raise ValueError("Phase duration_s must be > 0")
        if self.to_users < 0:
            raise ValueError("to_users must be >= 0")
        if self.type == "ramp" and self.from_users < 0:
            raise ValueError("from_users must be >= 0")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "duration_s": self.duration_s,
            "from_users": self.from_users,
            "to_users": self.to_users,
            "model": self.model,
        }


@dataclass
class LoadScenario:
    """Defines a complete load test scenario."""
    name: str
    test_ids: List[str]         # Test definition names to execute (round-robin per user)
    phases: List[LoadPhase]     # Ordered list of phases
    think_time_ms: int = 0      # Pause between iterations per virtual user
    bucket_s: int = 5           # Metrics aggregation bucket size in seconds
    max_duration_s: int = 3600  # Safety cap

    def total_duration_s(self) -> int:
        return sum(p.duration_s for p in self.phases)

    def validate(self):
        if not self.name:
            raise ValueError("Scenario name must not be empty")
        if not self.test_ids:
            raise ValueError("test_ids must not be empty")
        if not self.phases:
            raise ValueError("phases must not be empty")
        for phase in self.phases:
            phase.validate()
        total = self.total_duration_s()
        if total > self.max_duration_s:
            raise ValueError(
                f"Total scenario duration {total}s exceeds max_duration_s={self.max_duration_s}"
            )
        if self.bucket_s <= 0:
            raise ValueError("bucket_s must be > 0")

    def build_users_timeline(self) -> List[int]:
        """
        Compute target concurrency for each second t in [0, total_duration_s).
        Returns a list of integers (one per second).
        """
        timeline: List[int] = []
        for phase in self.phases:
            if phase.type == "steady":
                timeline.extend([phase.to_users] * phase.duration_s)
            elif phase.type == "ramp":
                n = phase.duration_s
                for i in range(n):
                    if n == 1:
                        users = phase.to_users
                    else:
                        users = round(
                            phase.from_users
                            + (phase.to_users - phase.from_users) * i / (n - 1)
                        )
                    timeline.append(max(0, users))
        return timeline

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "test_ids": self.test_ids,
            "phases": [p.to_dict() for p in self.phases],
            "think_time_ms": self.think_time_ms,
            "bucket_s": self.bucket_s,
            "total_duration_s": self.total_duration_s(),
        }


@dataclass
class LoadMetricBucket:
    """Aggregated metrics for one time bucket."""
    t_s: int            # Bucket start time (seconds from scenario start)
    ok: int = 0
    ko: int = 0
    active_users: int = 0
    mean_ms: float = 0.0
    p50_ms: float = 0.0
    p90_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "t_s": self.t_s,
            "ok": self.ok,
            "ko": self.ko,
            "active_users": self.active_users,
            "mean_ms": round(self.mean_ms, 1),
            "p50_ms": round(self.p50_ms, 1),
            "p90_ms": round(self.p90_ms, 1),
            "p99_ms": round(self.p99_ms, 1),
            "max_ms": round(self.max_ms, 1),
        }


@dataclass
class LoadTestSummary:
    """Per-test-id summary statistics over the full scenario."""
    test_id: str
    total: int = 0
    ok: int = 0
    ko: int = 0
    mean_ms: float = 0.0
    p50_ms: float = 0.0
    p90_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0
    error_rate_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "total": self.total,
            "ok": self.ok,
            "ko": self.ko,
            "mean_ms": round(self.mean_ms, 1),
            "p50_ms": round(self.p50_ms, 1),
            "p90_ms": round(self.p90_ms, 1),
            "p99_ms": round(self.p99_ms, 1),
            "max_ms": round(self.max_ms, 1),
            "error_rate_pct": round(self.error_rate_pct, 2),
        }


@dataclass
class LoadReport:
    """Final load test report containing all time-series data and summaries."""
    job_id: str
    scenario_name: str
    scenario: Optional[Dict[str, Any]] = None   # Original scenario definition
    status: str = "COMPLETED"                   # "COMPLETED" | "CANCELLED" | "FAILED"
    started_at: str = ""
    completed_at: str = ""
    total_duration_s: int = 0
    total_requests: int = 0
    total_ok: int = 0
    total_ko: int = 0
    buckets: List[LoadMetricBucket] = field(default_factory=list)
    summaries: List[LoadTestSummary] = field(default_factory=list)
    error_rate_pct: float = 0.0
    mean_ms: float = 0.0
    p50_ms: float = 0.0
    p90_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "scenario_name": self.scenario_name,
            "scenario": self.scenario,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration_s": self.total_duration_s,
            "total_requests": self.total_requests,
            "total_ok": self.total_ok,
            "total_ko": self.total_ko,
            "error_rate_pct": round(self.error_rate_pct, 2),
            "mean_ms": round(self.mean_ms, 1),
            "p50_ms": round(self.p50_ms, 1),
            "p90_ms": round(self.p90_ms, 1),
            "p99_ms": round(self.p99_ms, 1),
            "max_ms": round(self.max_ms, 1),
            "buckets": [b.to_dict() for b in self.buckets],
            "summaries": [s.to_dict() for s in self.summaries],
        }


def percentile(sorted_data: List[float], pct: int) -> float:
    """Linear-interpolation percentile on a pre-sorted list."""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * pct / 100
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return float(sorted_data[-1])
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])

