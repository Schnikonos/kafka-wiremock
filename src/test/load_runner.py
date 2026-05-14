"""
Closed-model load runner for Gatling-style load testing.

Each virtual user is an asyncio Task that offloads its test execution to a
ThreadPoolExecutor so heavy synchronous work (JSONPath eval, template rendering,
Kafka polling waits) never blocks the event loop.  This keeps:
  • asyncio.sleep(1.0) ticks firing on time → accurate active-user count
  • FastAPI GET /load-tests/{id} responding immediately (no timer starvation)
  • Progress reported as wall-clock %, not tick count

Architecture note: For future open-model support (inject_rate_per_s), replace
_user_loop scheduling with a token-bucket rate limiter and remove the
concurrency-cap logic.
"""
import asyncio
import logging
import time
import statistics as _statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from .load_scenario import (
    LoadMetricBucket,
    LoadReport,
    LoadScenario,
    LoadTestSummary,
    percentile,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BucketCollector  (unchanged — already thread-safe)
# ---------------------------------------------------------------------------

class BucketCollector:
    """
    Thread-safe aggregator that bins completed test results into time buckets.

    Each record is (elapsed_ms, ok: bool, test_id, active_users).  Buckets are
    keyed by  (t_s // bucket_s) * bucket_s  where t_s is seconds since the
    scenario started.  A bucket is "complete" (and can be flushed) once the
    current clock has moved past it.
    """

    def __init__(self, bucket_s: int):
        self.bucket_s = bucket_s
        self._lock = Lock()
        self._start_time: float = time.time()
        # open bucket data: {bucket_key: [(elapsed_ms, ok, active_users), ...]}
        self._open: Dict[int, List[Tuple[int, bool, int]]] = defaultdict(list)
        self._flushed: List[LoadMetricBucket] = []
        # per-test raw records for final summary: {test_id: [(elapsed_ms, ok), ...]}
        self._per_test: Dict[str, List[Tuple[int, bool]]] = defaultdict(list)

    # ------------------------------------------------------------------
    def record(self, elapsed_ms: int, ok: bool, test_id: str, active_users: int = 0):
        t_s = int(time.time() - self._start_time)
        bucket_key = (t_s // self.bucket_s) * self.bucket_s
        with self._lock:
            self._open[bucket_key].append((elapsed_ms, ok, active_users))
            self._per_test[test_id].append((elapsed_ms, ok))

    # ------------------------------------------------------------------
    def flush_completed(self, current_t_s: int):
        """Flush buckets whose window has closed (before the current window)."""
        current_key = (current_t_s // self.bucket_s) * self.bucket_s
        with self._lock:
            keys = sorted(k for k in self._open if k < current_key)
            for key in keys:
                records = self._open.pop(key)
                self._flushed.append(self._make_bucket(key, records))

    def flush_all(self):
        """Flush every remaining open bucket (called at scenario end)."""
        with self._lock:
            for key in sorted(self._open.keys()):
                records = self._open.pop(key)
                if records:
                    self._flushed.append(self._make_bucket(key, records))

    # ------------------------------------------------------------------
    def get_flushed_dicts(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [b.to_dict() for b in self._flushed]

    def get_per_test_summaries(self) -> List[LoadTestSummary]:
        with self._lock:
            summaries = []
            for test_id, records in self._per_test.items():
                if not records:
                    continue
                times = [r[0] for r in records]
                oks = sum(1 for r in records if r[1])
                kos = len(records) - oks
                srt = sorted(times)
                summaries.append(LoadTestSummary(
                    test_id=test_id,
                    total=len(records),
                    ok=oks,
                    ko=kos,
                    mean_ms=_statistics.mean(times) if times else 0.0,
                    p50_ms=percentile(srt, 50),
                    p90_ms=percentile(srt, 90),
                    p99_ms=percentile(srt, 99),
                    max_ms=float(max(times)) if times else 0.0,
                    error_rate_pct=(kos / len(records) * 100),
                ))
            return summaries

    def get_global_stats(self) -> Dict[str, float]:
        """Aggregate elapsed_ms across ALL tests for the overall summary row."""
        with self._lock:
            all_times = [
                r[0]
                for recs in self._per_test.values()
                for r in recs
            ]
        if not all_times:
            return {"mean_ms": 0, "p50_ms": 0, "p90_ms": 0, "p99_ms": 0, "max_ms": 0}
        srt = sorted(all_times)
        return {
            "mean_ms": _statistics.mean(all_times),
            "p50_ms": percentile(srt, 50),
            "p90_ms": percentile(srt, 90),
            "p99_ms": percentile(srt, 99),
            "max_ms": float(max(all_times)),
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _make_bucket(t_s: int, records: List[Tuple[int, bool, int]]) -> LoadMetricBucket:
        times = [r[0] for r in records]
        oks = sum(1 for r in records if r[1])
        kos = len(records) - oks
        max_users = max((r[2] for r in records), default=0)
        srt = sorted(times)
        return LoadMetricBucket(
            t_s=t_s,
            ok=oks,
            ko=kos,
            active_users=max_users,
            mean_ms=_statistics.mean(times) if times else 0.0,
            p50_ms=percentile(srt, 50),
            p90_ms=percentile(srt, 90),
            p99_ms=percentile(srt, 99),
            max_ms=float(max(times)) if times else 0.0,
        )


# ---------------------------------------------------------------------------
# LoadRunner
# ---------------------------------------------------------------------------

class LoadRunner:
    """
    Executes a closed-model load scenario.

    KEY DESIGN: test execution runs in a ThreadPoolExecutor, NOT in the asyncio
    event loop.  This is critical:
      - asyncio.sleep(1.0) ticks always fire on time
      - GET /load-tests/{id} poll requests are never queued behind test work
      - progress_pct is wall-clock based — always accurate

    Virtual user lifetime:
      asyncio Task (_user_loop)
        └── awaits loop.run_in_executor(thread_pool, _run_test_sync)
              └── thread: asyncio.run(_run_test_async)
                    └── test_executor.run_test(...)
    """

    def __init__(self, test_executor, test_loader):
        self.test_executor = test_executor
        self.test_loader = test_loader

    # ------------------------------------------------------------------
    async def run(
        self,
        scenario: LoadScenario,
        job_id: str,
        jobs: Dict[str, Any],
    ) -> LoadReport:
        started_at = datetime.now(timezone.utc).isoformat() + "Z"
        collector = BucketCollector(bucket_s=scenario.bucket_s)

        jobs[job_id].update({
            "status": "RUNNING",
            "started_at": started_at,
            "active_users": 0,
            "progress_pct": 0,
            "elapsed_s": 0,
            "buckets": [],
            "collector": collector,
        })

        # Resolve test definitions up-front
        all_tests = self.test_loader.discover_tests()
        test_map = {t.name: t for t in all_tests}
        selected = [test_map[tid] for tid in scenario.test_ids if tid in test_map]
        missing = [tid for tid in scenario.test_ids if tid not in test_map]
        if missing:
            logger.warning(f"Load '{scenario.name}': test IDs not found — {missing}")
        if not selected:
            raise ValueError(f"No valid tests found for scenario '{scenario.name}'")

        timeline = scenario.build_users_timeline()
        total_s = len(timeline)

        # Size the thread pool to the peak concurrency + a small buffer so
        # ramp-ups never queue.  Each virtual user occupies exactly one thread
        # while a test is executing.
        peak_users = max(timeline) if timeline else 1
        pool_size = max(peak_users + 4, 8)
        logger.info(
            f"Load job {job_id}: scenario='{scenario.name}' "
            f"total={total_s}s peak={peak_users} users thread_pool={pool_size}"
        )

        start_time = time.time()
        active_tasks: List[asyncio.Task] = []
        final_status = "COMPLETED"
        loop = asyncio.get_event_loop()

        with ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix=f"load-{job_id[:8]}") as thread_pool:
            try:
                # Self-correcting tick loop: compute next_tick from wall clock so that
                # work inside the tick (task bookkeeping) doesn't accumulate drift.
                next_tick = start_time + 1.0

                for t_idx, target in enumerate(timeline):
                    # Reap finished tasks
                    active_tasks = [t for t in active_tasks if not t.done()]

                    # Scale up
                    while len(active_tasks) < target:
                        task = asyncio.create_task(
                            self._user_loop(
                                selected, scenario, collector,
                                jobs, job_id, loop, thread_pool,
                            )
                        )
                        active_tasks.append(task)

                    # Scale down (cancel excess — they'll finish current test run in thread)
                    while len(active_tasks) > target:
                        task = active_tasks.pop()
                        task.cancel()

                    # Wall-clock progress (accurate even if ticks drift slightly)
                    elapsed_t = time.time() - start_time
                    collector.flush_completed(int(elapsed_t))

                    jobs[job_id]["active_users"] = len(active_tasks)
                    jobs[job_id]["progress_pct"] = min(99, int(elapsed_t / total_s * 100))
                    jobs[job_id]["elapsed_s"] = int(elapsed_t)
                    jobs[job_id]["buckets"] = collector.get_flushed_dicts()

                    # Sleep until the next 1-second wall-clock tick (self-correcting)
                    sleep_s = max(0.0, next_tick - time.time())
                    next_tick += 1.0
                    await asyncio.sleep(sleep_s)

            except asyncio.CancelledError:
                logger.info(f"Load job {job_id} cancelled")
                final_status = "CANCELLED"
            except Exception as exc:
                logger.error(f"Load job {job_id} error: {exc}", exc_info=True)
                final_status = "FAILED"
                jobs[job_id]["error"] = str(exc)
            finally:
                # Cancel all user tasks; their threads will drain naturally
                for task in active_tasks:
                    task.cancel()
                if active_tasks:
                    await asyncio.gather(*active_tasks, return_exceptions=True)

        # thread_pool.shutdown(wait=True) is called by context manager —
        # all in-flight test threads are allowed to finish cleanly.

        elapsed_total = int(time.time() - start_time)
        collector.flush_all()

        completed_at = datetime.now(timezone.utc).isoformat() + "Z"
        summaries = collector.get_per_test_summaries()
        global_stats = collector.get_global_stats()

        total_ok = sum(b.ok for b in collector._flushed)
        total_ko = sum(b.ko for b in collector._flushed)
        total_req = total_ok + total_ko

        report = LoadReport(
            job_id=job_id,
            scenario_name=scenario.name,
            scenario=scenario.to_dict(),
            status=final_status,
            started_at=started_at,
            completed_at=completed_at,
            total_duration_s=elapsed_total,
            total_requests=total_req,
            total_ok=total_ok,
            total_ko=total_ko,
            buckets=list(collector._flushed),
            summaries=summaries,
            error_rate_pct=(total_ko / total_req * 100) if total_req > 0 else 0.0,
            mean_ms=global_stats["mean_ms"],
            p50_ms=global_stats["p50_ms"],
            p90_ms=global_stats["p90_ms"],
            p99_ms=global_stats["p99_ms"],
            max_ms=global_stats["max_ms"],
        )

        jobs[job_id]["status"] = final_status
        jobs[job_id]["progress_pct"] = 100
        jobs[job_id]["elapsed_s"] = elapsed_total
        jobs[job_id]["buckets"] = [b.to_dict() for b in report.buckets]
        jobs[job_id]["report"] = report.to_dict()
        return report

    # ------------------------------------------------------------------
    async def _user_loop(
        self,
        tests,
        scenario: LoadScenario,
        collector: BucketCollector,
        jobs: Dict[str, Any],
        job_id: str,
        loop: asyncio.AbstractEventLoop,
        thread_pool: ThreadPoolExecutor,
    ):
        """
        Virtual user coroutine.

        Runs tests one at a time, each in a dedicated thread via run_in_executor.
        This keeps the asyncio event loop free — only the scheduling overhead
        (task creation, await, think_time sleep) runs in the event loop.
        """
        test_index = 0
        while True:
            try:
                test_def = tests[test_index % len(tests)]
                test_index += 1

                t_start = time.time()
                ok = False

                # Run the full async test in a worker thread with its own event loop.
                # This prevents ANY test work (Kafka polling, JSON parsing, etc.)
                # from blocking the main event loop.
                try:
                    executor = self.test_executor   # local ref for closure
                    fp = Path(test_def.file_path) if test_def.file_path else None

                    def _run_in_thread(td=test_def, file_path=fp):
                        """Executed in thread_pool; creates its own asyncio loop."""
                        return asyncio.run(
                            executor.run_test(
                                td,
                                file_path,
                                verbose=False,
                                force_run=True,
                            )
                        )

                    result = await loop.run_in_executor(thread_pool, _run_in_thread)
                    ok = result.status == "PASSED"

                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug(f"Load user error ({test_def.name}): {exc}")
                    ok = False

                elapsed_ms = int((time.time() - t_start) * 1000)
                active = jobs.get(job_id, {}).get("active_users", 0)
                collector.record(elapsed_ms, ok, test_def.name, active)

                if scenario.think_time_ms > 0:
                    await asyncio.sleep(scenario.think_time_ms / 1000.0)

            except asyncio.CancelledError:
                return

