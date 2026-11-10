"""Git update checks and application helpers for Phase 15."""

import subprocess
from datetime import datetime, timezone

UPDATE_STATUSES = ('available', 'up_to_date', 'error', 'unknown')

CHECK_COMMAND = (
    'cd "{app_dir}" 2>/dev/null && git fetch origin 2>&1 && '
    'LOCAL=$(git rev-parse HEAD 2>/dev/null) && '
    'REMOTE=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master 2>/dev/null) && '
    'if [ "$LOCAL" = "$REMOTE" ]; then echo "UP_TO_DATE"; '
    'else echo "UPDATE_AVAILABLE"; fi'
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def parse_update_output(output):
    text = (output or '').strip()
    if 'UPDATE_AVAILABLE' in text:
        return 'available'
    if 'UP_TO_DATE' in text:
        return 'up_to_date'
    if not text or 'ERROR' in text.upper():
        return 'error'
    return 'unknown'


def classify_update(local_revision, remote_revision):
    local = (local_revision or '').strip()
    remote = (remote_revision or '').strip()
    if not local or not remote:
        return 'unknown'
    return 'up_to_date' if local == remote else 'available'


def check_for_updates(app_dir, runner=subprocess.run, timeout=30):
    command = CHECK_COMMAND.format(app_dir=app_dir)
    try:
        result = runner(
            ['bash', '-c', command], capture_output=True, text=True, timeout=timeout
        )
        output = ((result.stdout or '') + (result.stderr or '')).strip()
        status = parse_update_output(output)
        if status == 'error' and getattr(result, 'returncode', 0) != 0:
            status = 'error'
    except Exception as exc:
        output = f'ERROR: {exc}'
        status = 'error'
    return {'status': status, 'output': output, 'checked_at': _now()}


def apply_update(app_dir, runner=subprocess.run, timeout=120):
    try:
        result = runner(
            ['git', '-C', app_dir, 'pull', '--ff-only'],
            capture_output=True, text=True, timeout=timeout,
        )
        output = ((result.stdout or '') + (result.stderr or '')).strip()
        ok = getattr(result, 'returncode', 1) == 0
        return {
            'status': 'updated' if ok else 'error',
            'output': output,
            'applied_at': _now(),
        }
    except Exception as exc:
        return {'status': 'error', 'output': str(exc), 'applied_at': _now()}
