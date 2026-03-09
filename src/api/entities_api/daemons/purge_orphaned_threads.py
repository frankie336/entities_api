# src/api/entities_api/daemons/purge_orphaned_threads.py
#!/usr/bin/env python3
"""
purge_orphaned_threads.py
─────────────────────────
GDPR housekeeping daemon — purges threads whose owner was erased.

After a user erasure, Thread.owner_id is SET NULL by the FK constraint.
Those threads (and their messages) are inaccessible via ownership guards but
persist in the DB indefinitely.  This daemon hard-deletes them once they are
older than ORPHAN_THREAD_RETENTION_DAYS.

Key schema facts (from models.py)
──────────────────────────────────
  Thread.created_at  — Integer (Unix epoch seconds), NOT a DateTime column.
  Message.thread_id  — plain String, intentionally has NO FK constraint.
                       There is no DB-level cascade; messages must be deleted
                       manually before (or alongside) their threads.
  Thread.owner_id    — SET NULL on user deletion (FK: users.id).

Deletion order (safest first)
──────────────────────────────
  1. DELETE messages WHERE thread_id IN (batch)
  2. DELETE threads  WHERE id        IN (batch)

What is never touched
──────────────────────
  Threads with owner_id IS NOT NULL (live / shared threads)
  audit_logs  (compliance trail — never modified by this daemon)

Environment variables  (same .env the API uses)
────────────────────────────────────────────────
  DATABASE_URL                  — resolved automatically via database.py
  ORPHAN_THREAD_RETENTION_DAYS  — days to retain orphaned threads (default: 30)
  CHECK_INTERVAL_SECONDS        — daemon polling interval in seconds  (default: 3600)
  PURGE_BATCH_SIZE              — rows per batch deletion             (default: 200)
  DRY_RUN                       — "true" to log without deleting      (default: false)

Usage
─────
  # Safe dry-run
  DRY_RUN=true python /app/src/api/entities_api/daemons/purge_orphaned_threads.py --once

  # One-shot (cron / CI)
  python /app/src/api/entities_api/daemons/purge_orphaned_threads.py --once

  # Daemon (background service / supervisord sidecar)
  python /app/src/api/entities_api/daemons/purge_orphaned_threads.py

Supervisord stanza (add to supervisord.conf)
────────────────────────────────────────────
  [program:purge_orphaned_threads]
  command=python /app/src/api/entities_api/daemons/purge_orphaned_threads.py
  directory=/app
  autostart=true
  autorestart=true
  startretries=5
  startsecs=10
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  stderr_logfile=/dev/stderr
  stderr_logfile_maxbytes=0
  environment=PYTHONPATH="/app/src/api"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()

# ── Reuse the centralised engine / session factory ────────────────────────────
# database.py handles running_in_docker() URL resolution automatically.
from entities_api.db.database import SessionLocal, wait_for_databases

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("purge-orphaned-threads")

# ── Config ────────────────────────────────────────────────────────────────────

RETENTION_DAYS: int = int(os.getenv("ORPHAN_THREAD_RETENTION_DAYS", "30"))
CHECK_INTERVAL: int = int(os.getenv("CHECK_INTERVAL_SECONDS", "3600"))
BATCH_SIZE: int = int(os.getenv("PURGE_BATCH_SIZE", "200"))
DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() == "true"


# ── Core logic ────────────────────────────────────────────────────────────────


def purge_orphaned_threads(session) -> tuple[int, int]:
    """
    Delete orphaned threads older than the retention window, plus their messages.

    Thread.created_at is stored as Unix epoch seconds (Integer column), so the
    cutoff is an integer, not a datetime.

    Message.thread_id carries no FK constraint — there is no DB-level cascade.
    Messages are deleted explicitly in the same transaction as their threads.

    Returns (threads_attempted, threads_deleted).
    """
    cutoff_epoch: int = int(
        (datetime.now(tz=timezone.utc) - timedelta(days=RETENTION_DAYS)).timestamp()
    )

    # ── Count qualifying threads ──────────────────────────────────────────────
    count_row = session.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM   threads
            WHERE  owner_id   IS NULL
              AND  created_at  < :cutoff
            """
        ),
        {"cutoff": cutoff_epoch},
    ).fetchone()

    total = count_row.cnt if count_row else 0
    log.info(
        "Orphaned threads older than %d day(s): %d  (cutoff epoch=%d)",
        RETENTION_DAYS,
        total,
        cutoff_epoch,
    )

    if total == 0:
        log.info("Nothing to purge — exiting cleanly.")
        return 0, 0

    if DRY_RUN:
        log.info("[DRY_RUN] Would delete %d thread(s) and their messages.", total)
        return total, total

    # ── Batch deletion loop ───────────────────────────────────────────────────
    threads_deleted = 0
    messages_deleted = 0

    while True:
        # Fetch next batch of orphaned thread IDs
        rows = session.execute(
            text(
                """
                SELECT id
                FROM   threads
                WHERE  owner_id   IS NULL
                  AND  created_at  < :cutoff
                LIMIT  :batch_size
                """
            ),
            {"cutoff": cutoff_epoch, "batch_size": BATCH_SIZE},
        ).fetchall()

        if not rows:
            break

        batch_ids = [r.id for r in rows]

        # SQLAlchemy text() doesn't support list binding natively — use named
        # params :id_0, :id_1, … to build a safe IN-list.
        id_params = {f"id_{i}": v for i, v in enumerate(batch_ids)}
        in_clause = ", ".join(f":id_{i}" for i in range(len(batch_ids)))

        try:
            # Step 1: delete messages (no FK cascade on Message.thread_id)
            msg_result = session.execute(
                text(f"DELETE FROM messages WHERE thread_id IN ({in_clause})"),
                id_params,
            )

            # Step 2: delete the thread rows themselves
            thr_result = session.execute(
                text(f"DELETE FROM threads WHERE id IN ({in_clause})"),
                id_params,
            )

            session.commit()

            msgs_in_batch = msg_result.rowcount
            threads_in_batch = thr_result.rowcount

            threads_deleted += threads_in_batch
            messages_deleted += msgs_in_batch

            log.info(
                "Batch: threads=%d  messages=%d  (running totals: %d / %d)",
                threads_in_batch,
                msgs_in_batch,
                threads_deleted,
                messages_deleted,
            )

        except Exception as exc:
            session.rollback()
            log.error("Batch failed — rolled back | %s", exc, exc_info=True)
            raise

        if len(batch_ids) < BATCH_SIZE:
            break  # Final partial batch — nothing more to do

        time.sleep(0.05)  # Brief pause to avoid saturating the DB under load

    log.info(
        "Purge complete — threads deleted: %d  messages deleted: %d",
        threads_deleted,
        messages_deleted,
    )
    return threads_deleted, threads_deleted


# ── Entry points ──────────────────────────────────────────────────────────────


def run_once() -> None:
    log.info(
        "=== One-shot orphaned-thread purge | retention=%dd | DRY_RUN=%s ===",
        RETENTION_DAYS,
        DRY_RUN,
    )
    db = SessionLocal()
    try:
        attempted, deleted = purge_orphaned_threads(db)
    finally:
        db.close()
    log.info("Done. %d/%d thread(s) purged.", deleted, attempted)


def run_daemon() -> None:
    log.info(
        "=== Orphaned-thread purge daemon started"
        " | interval=%ds | retention=%dd | DRY_RUN=%s ===",
        CHECK_INTERVAL,
        RETENTION_DAYS,
        DRY_RUN,
    )
    while True:
        try:
            db = SessionLocal()
            try:
                attempted, deleted = purge_orphaned_threads(db)
            finally:
                db.close()
            log.info("Cycle complete. %d/%d thread(s) purged.", deleted, attempted)
        except Exception as exc:
            log.error("Unexpected error during purge cycle: %s", exc, exc_info=True)
        log.info("Sleeping %d seconds until next cycle…", CHECK_INTERVAL)
        time.sleep(CHECK_INTERVAL)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orphaned thread cleanup daemon")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single pass then exit (default: run as daemon)",
    )
    parser.add_argument(
        "--skip-wait",
        action="store_true",
        help="Skip the DB readiness check (useful if DB is already confirmed up)",
    )
    args = parser.parse_args()

    if not args.skip_wait:
        wait_for_databases()

    if args.once:
        run_once()
    else:
        run_daemon()
