"""Thread-safe in-process event bus used by the live SSE alert stream."""

import json
import queue
import threading
import time
from collections import deque

_subscribers = set()
_lock = threading.Lock()
_history = deque(maxlen=250)
_sequence = 0


def publish(event_type, data=None):
    """Broadcast an event to every live subscriber and return the envelope."""
    global _sequence
    payload = dict(data or {})
    with _lock:
        _sequence += 1
        event = {
            'id': _sequence,
            'type': str(event_type or 'message'),
            'data': payload,
            'created_at': time.time(),
        }
        _history.append(event)
        subscribers = list(_subscribers)
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            try:
                subscriber.get_nowait()
                subscriber.put_nowait(event)
            except (queue.Empty, queue.Full):
                pass
        except Exception:
            pass
    return event


def subscribe(maxsize=100):
    audience = queue.Queue(maxsize=max(1, int(maxsize)))
    with _lock:
        _subscribers.add(audience)
    return audience


def unsubscribe(audience):
    with _lock:
        _subscribers.discard(audience)


def subscriber_count():
    with _lock:
        return len(_subscribers)


def recent(limit=50):
    with _lock:
        items = list(_history)
    return items[-max(1, int(limit)):]


def reset():
    """Clear subscribers and history. Intended for tests and process restarts."""
    global _sequence
    with _lock:
        _subscribers.clear()
        _history.clear()
        _sequence = 0


def format_sse(event):
    """Render an event envelope as a Server-Sent Events frame."""
    envelope = dict(event or {})
    event_id = envelope.get('id', envelope.get('seq', 0))
    event_type = envelope.get('type', 'message')
    data = envelope.get('data', {})
    return (
        f"id: {event_id}\n"
        f"event: {event_type}\n"
        f"data: {json.dumps(data, default=str, separators=(',', ':'))}\n\n"
    )
