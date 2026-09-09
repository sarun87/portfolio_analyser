"""In-process, cancellable price-refresh jobs.

The encrypted database deliberately has one SQLite connection.  This module
therefore snapshots work and fetches quotes outside it; only recording a quote
uses ``get_connection``.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from backend.app.db.database import get_connection
from backend.app.services.models import PriceRefreshJobStatus, PriceRefreshResult
from backend.app.services.price_service import apply_quote_result, fetch_security_quote


@dataclass
class _Job:
    job_id: str
    items: list[tuple[int, str, str | None]]
    status: str = "queued"
    completed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    current_symbols: set[str] = field(default_factory=set)
    results: list[PriceRefreshResult] = field(default_factory=list)
    cancelled: bool = False


class PriceRefreshJobManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active: _Job | None = None
        self._jobs: dict[str, _Job] = {}

    def start(self) -> PriceRefreshJobStatus:
        # Avoid making an unnecessary database request for a duplicate start.
        # The second check below still closes the race between this check and
        # taking the snapshot.
        with self._lock:
            if self._active and self._active.status in {"queued", "running"}:
                raise RuntimeError("A price refresh job is already active.")
        # Snapshot first, while the DB is unlocked and only for a short read.
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT DISTINCT s.id, s.symbol, s.exchange FROM securities s
                JOIN positions p ON p.security_id = s.id
                WHERE s.price_refresh_supported = 1 AND s.symbol IS NOT NULL
                ORDER BY s.symbol
            """).fetchall()
        with self._lock:
            if self._active and self._active.status in {"queued", "running"}:
                raise RuntimeError("A price refresh job is already active.")
            job = _Job(str(uuid.uuid4()), [(int(r["id"]), r["symbol"], r["exchange"]) for r in rows])
            self._active = job
            self._jobs[job.job_id] = job
            thread = threading.Thread(target=self._run, args=(job,), daemon=True, name="price-refresh")
            thread.start()
            return self._status(job)

    def get(self, job_id: str) -> PriceRefreshJobStatus | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return self._status(job) if job else None

    def active(self) -> PriceRefreshJobStatus | None:
        with self._lock:
            return self._status(self._active) if self._active and self._active.status in {"queued", "running"} else None

    def cancel(self, job_id: str | None = None) -> PriceRefreshJobStatus | None:
        with self._lock:
            job = self._jobs.get(job_id) if job_id else self._active
            if not job:
                return None
            if job.status in {"queued", "running"}:
                job.cancelled = True
                job.status = "cancelled"
                # Nothing not already committed will be applied after this
                # point, including work currently in a network call.
                job.skipped = len(job.items) - job.completed
                job.current_symbols.clear()
                completed_ids = {result.security_id for result in job.results}
                job.results.extend(
                    PriceRefreshResult(
                        security_id=security_id, symbol=symbol, refreshed=False,
                        message="Refresh cancelled.",
                    )
                    for security_id, symbol, _exchange in job.items
                    if security_id not in completed_ids
                )
            return self._status(job)

    def shutdown(self) -> None:
        self.cancel()

    def _run(self, job: _Job) -> None:
        with self._lock:
            if job.cancelled:
                return
            job.status = "running"
        if not job.items:
            with self._lock:
                job.status = "completed"
            return
        try:
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix="quote-fetch") as executor:
                iterator = iter(job.items)
                futures = {}
                def submit_next() -> bool:
                    with self._lock:
                        if job.cancelled:
                            return False
                    try:
                        item = next(iterator)
                    except StopIteration:
                        return False
                    future = executor.submit(fetch_security_quote, *item)
                    futures[future] = item
                    with self._lock:
                        job.current_symbols.add(item[1])
                    return True
                for _ in range(3):
                    if not submit_next(): break
                while futures:
                    done, _ = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        item = futures.pop(future)
                        with self._lock:
                            job.current_symbols.discard(item[1])
                            cancelled = job.cancelled
                        if cancelled:
                            continue
                        try:
                            result = future.result()
                        except Exception as exc:
                            result = PriceRefreshResult(security_id=item[0], symbol=item[1], refreshed=False, message=str(exc))
                        # Hold manager lock across the cancellation check and commit so lock()
                        # cannot allow a write after it has marked this job cancelled.
                        with self._lock:
                            if job.cancelled:
                                continue
                            if result.refreshed:
                                with get_connection() as conn:
                                    result = apply_quote_result(conn, result)
                            job.results.append(result)
                            job.completed += 1
                            if result.refreshed: job.succeeded += 1
                            else: job.failed += 1
                        submit_next()
            with self._lock:
                if not job.cancelled:
                    job.status = "completed"
        except Exception as exc:
            with self._lock:
                if not job.cancelled:
                    job.status = "failed"
                    job.results.append(PriceRefreshResult(security_id=0, symbol=None, refreshed=False, message=str(exc)))
                    job.failed += 1

    @staticmethod
    def _status(job: _Job) -> PriceRefreshJobStatus:
        return PriceRefreshJobStatus(job_id=job.job_id, status=job.status, total=len(job.items), completed=job.completed,
            succeeded=job.succeeded, failed=job.failed, skipped=job.skipped, current_symbols=sorted(job.current_symbols), results=list(job.results))


price_refresh_jobs = PriceRefreshJobManager()
