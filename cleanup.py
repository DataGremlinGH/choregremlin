#!/usr/bin/env python3
"""
ChoreGremlin Chore Retention Cleanup
Deletes chore logs older than 1 year. Runs daily via systemd timer.
"""

import sqlite3
import os
from datetime import datetime, timedelta

DATA_DIR = os.environ.get('CHOREGREMLIN_DATA_DIR',
                          os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data'))
DB_PATH = os.path.join(DATA_DIR, 'choregremlin.db')

RETENTION_DAYS = 365

def cleanup():
    if not os.path.exists(DB_PATH):
        print("Database not found. Nothing to clean up.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).strftime('%Y-%m-%d %H:%M:%S')

    result = conn.execute(
        "DELETE FROM chore_logs WHERE status='completed' AND finished_at < ?",
        (cutoff,)
    )
    chore_deleted = result.rowcount

    result = conn.execute(
        "DELETE FROM chore_logs WHERE status='in_progress' AND started_at < ?",
        (cutoff,)
    )
    stale_deleted = result.rowcount

    result = conn.execute(
        "DELETE FROM activity_log WHERE created_at < ?",
        (cutoff,)
    )
    activity_deleted = result.rowcount

    result = conn.execute(
        "DELETE FROM payments WHERE log_id IS NOT NULL AND log_id NOT IN (SELECT id FROM chore_logs)"
    )
    orphan_payments = result.rowcount

    conn.commit()
    conn.execute("VACUUM")
    conn.close()

    print(f"Cleanup complete: {chore_deleted} old chore logs, {stale_deleted} stale logs, "
          f"{activity_deleted} activity entries, {orphan_payments} orphaned payments removed.")
    print(f"Retention period: {RETENTION_DAYS} days (records older than {cutoff} were deleted).")

if __name__ == '__main__':
    cleanup()
